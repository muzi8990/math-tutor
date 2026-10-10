"""Synchronous per-session tutor; one instance represents one conversation."""

from pathlib import Path
from threading import RLock
from time import perf_counter
import base64
import json

from google import genai
from google.genai import errors, types
import httpx
from pydantic import ValidationError

from .images import load_image
from .prompts import build_prompt
from .settings import Settings
from .analysis import ProblemAnalysis, build_analysis_prompt
from .quality import ModelQualityReview, QualityReport, REVIEW_PROMPT, build_repair_prompt, check_analysis, sensitive_strings
from .logging import logger, safe_error


class TutorError(RuntimeError):
    """Model failure or conversation resource limit."""
    def __init__(self, message, *, status_code=None, error_code="model"):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class MathTutor:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        grade: int | None = None,
        max_turns: int | None = None,
        settings: Settings | None = None,
        client: genai.Client | None = None,
    ):
        overrides = {key: value for key, value in {
            "api_key": api_key, "model": model, "grade": grade, "max_turns": max_turns,
        }.items() if value is not None}
        # Revalidate overrides without reloading sources or mutating caller settings.
        self.settings = (
            Settings.model_validate({**settings.model_dump(), **overrides})
            if settings is not None else Settings(**overrides)
        )
        self.model = self.settings.model
        self.grade = self.settings.grade
        self.max_turns = self.settings.max_turns
        self._history: list[types.Content] = []
        self._lock = RLock()
        self._closed = False
        self._owns_client = client is None
        if client is None:
            key = self.settings.api_key
            if key is None:
                raise ValueError("请设置 GOOGLE_API_KEY 或 GEMINI_API_KEY。")
            client = genai.Client(
                api_key=key.get_secret_value(),
                http_options=types.HttpOptions(timeout=self.settings.timeout_ms),
            )
        self._client = client

    @property
    def turn_count(self) -> int:
        with self._lock:
            return len(self._history) // 2

    def reset(self) -> None:
        """Discard this instance's in-memory messages and images."""
        with self._lock:
            self._history.clear()

    def chat(self, text: str = "", *, image: str | Path | None = None, mode: str = "hint") -> str:
        """Send a turn, committing history only after a complete text response."""
        with self._lock:
            if self.turn_count >= self.max_turns:
                raise TutorError("会话已达到轮数上限，请调用 reset() 或在 CLI 输入 /reset 开始新题。")
            prompt = build_prompt(mode, self.grade)
            user = self._make_user(text, image)
            answer = self._generate([*self._history, user], prompt)
            self._history.extend([user, types.Content(role="model", parts=[types.Part.from_text(text=answer)])])
            return answer

    def analyze_image(self, image: str | Path) -> str:
        """Read a photo without changing the current conversation."""
        with self._lock:
            user = self._make_user("请识别这张数学题图片中的题干与已有作答。", image)
            return self._generate([user], build_prompt("read", self.grade))

    def analyze_problem(self, text: str = "", *, image: str | Path | None = None) -> ProblemAnalysis:
        """Return knowledge points and linked solution steps without changing chat history."""
        with self._lock:
            user = self._make_user(text, image)
            answer = self._generate(
                [user], build_analysis_prompt(self.grade), response_schema=ProblemAnalysis,
            )
            result = self._parse_analysis(answer)
            return self._check_quality(user, result)

    def _parse_analysis(self, answer):
        try:
            return ProblemAnalysis.model_validate_json(answer)
        except ValidationError as exc:
            logger.bind(event="analysis.invalid", model=self.model, error_count=exc.error_count()).warning("Analysis failed schema or knowledge-reference validation")
            raise TutorError("模型分析未通过结构或知识点引用校验，请重试或确认题目。", error_code="schema") from exc

    @staticmethod
    def _unconfirmed_analysis(result):
        return ProblemAnalysis(
            status="needs_clarification", problem_text=result.problem_text,
            core_knowledge_points=[], detailed_knowledge_points=[], steps=[], answer=None,
            clarifications=["本次解答的计算或关键条件暂未通过质量核验，请稍后重新分析或请老师核对题目。"],
        )

    def _review_quality(self, user, result, report):
        payload = {"candidate": result.model_dump(), "deterministic_checks": report.model_dump()}
        context = types.Content(role="user", parts=[types.Part.from_text(text=json.dumps(payload, ensure_ascii=False))])
        answer = self._generate([user, context], REVIEW_PROMPT, response_schema=ModelQualityReview, sensitive_texts=list(sensitive_strings(payload)))
        try:
            reviewed = ModelQualityReview.model_validate_json(answer)
            indexes = {step.index for step in result.steps}
            if any(issue.step_index is not None and issue.step_index not in indexes for issue in reviewed.issues):
                raise ValueError("审查引用了不存在的步骤。")
        except (ValidationError, ValueError) as exc:
            raise TutorError("质量复核结果未通过校验。", error_code="quality_schema") from exc
        return QualityReport(**reviewed.model_dump(), checked_equalities=report.checked_equalities,
                             unchecked_formulas=report.unchecked_formulas, requires_model_review=report.requires_model_review)

    def _check_quality(self, user, result):
        sticky_review = False
        numeric_error_seen = False
        for repairs in range(self.settings.quality_max_repairs + 1):
            if result.status != "solved":
                return result
            report = check_analysis(result)
            sticky_review = sticky_review or report.requires_model_review or any(issue.code != "arithmetic_error" for issue in report.issues)
            numeric_error_seen = numeric_error_seen or any(issue.code == "arithmetic_error" for issue in report.issues)
            review_mode = self.settings.quality_model_review
            if repairs and numeric_error_seen and not report.checked_equalities and review_mode == "off":
                return self._unconfirmed_analysis(result)
            if report.status == "passed" and (review_mode == "always" or (review_mode == "on_risk" and sticky_review)):
                try:
                    report = self._review_quality(user, result, report)
                except TutorError as exc:
                    logger.bind(event="quality.review_failed", error_code=exc.error_code).warning("Solution quality review could not complete")
                    return self._unconfirmed_analysis(result)
            logger.bind(event="quality.checked", status=report.status, checked_equalities=report.checked_equalities,
                        unchecked_formulas=report.unchecked_formulas, issue_codes=[issue.code for issue in report.issues],
                        repairs=repairs).info("Solution quality checks completed")
            if report.status == "passed":
                return result
            if report.status == "needs_confirmation" or repairs >= self.settings.quality_max_repairs:
                return self._unconfirmed_analysis(result)
            payload = {"candidate": result.model_dump(), "quality_issues": report.model_dump()}
            context = types.Content(role="user", parts=[types.Part.from_text(text=json.dumps(payload, ensure_ascii=False))])
            try:
                answer = self._generate([user, context], build_repair_prompt(build_analysis_prompt(self.grade)),
                                        response_schema=ProblemAnalysis, sensitive_texts=list(sensitive_strings(payload)))
                result = self._parse_analysis(answer)
            except TutorError as exc:
                logger.bind(event="quality.repair_failed", error_code=exc.error_code).warning("Solution repair could not complete")
                return self._unconfirmed_analysis(result)
        return self._unconfirmed_analysis(result)

    @staticmethod
    def _make_user(text: str, image: str | Path | None) -> types.Content:
        if not isinstance(text, str):
            raise ValueError("text 必须为字符串。")
        text = text.strip()
        if not text and image is None:
            raise ValueError("请提供文字或题目图片。")
        if len(text) > 20_000:
            raise ValueError("单次输入过长，请限制在 20000 字符以内。")
        parts = [types.Part.from_text(text=text or "请帮我理解这张题目图片。")]
        if image is not None:
            data, mime = load_image(image)
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        return types.Content(role="user", parts=parts)

    def evaluate_submission(self, analysis: dict, text: str, *, image=None):
        """Judge actual student work using a standalone structured request."""
        import json
        from .mistakes.diagnosis import Judgment, JUDGMENT_PROMPT
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)
        with self._lock:
            user = self._make_user(text or "请评阅作答图片。", image)
            user.parts.insert(0, types.Part.from_text(text="参考分析：" + json.dumps(analysis, ensure_ascii=False)))
            answer = self._generate([user], JUDGMENT_PROMPT, response_schema=Judgment, sensitive_texts=list(strings(analysis)))
            try:
                return Judgment.model_validate_json(answer)
            except ValidationError as exc:
                logger.bind(event="judgment.invalid", error_count=exc.error_count()).warning("Judgment failed schema validation")
                raise TutorError("模型判定未通过结构校验，请重试。", error_code="schema") from exc

    def _generate(self, contents: list[types.Content], prompt: str, *, response_schema=None, sensitive_texts=()) -> str:
        if self._closed:
            raise TutorError("辅导实例已关闭，请创建新的 MathTutor。")
        config = types.GenerateContentConfig(
            system_instruction=prompt,
            temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_output_tokens,
            # Pass native JSON Schema unchanged; the SDK's response_schema
            # converter rewrites additionalProperties to an unsupported field.
            **({"response_mime_type": "application/json",
                "response_json_schema": response_schema.model_json_schema()}
               if response_schema is not None else {}),
        )
        started = perf_counter()
        fields = {"model": self.model, "structured": response_schema is not None, "message_count": len(contents)}
        logger.bind(event="model.start", **fields).debug("Gemini request started")
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
        except errors.APIError as exc:
            texts = [part.text for content in contents for part in content.parts or [] if part.text]
            texts.extend(sensitive_texts)
            images = [base64.b64encode(part.inline_data.data).decode() for content in contents for part in content.parts or [] if part.inline_data and part.inline_data.data]
            secret = self.settings.api_key.get_secret_value() if self.settings.api_key else None
            detail = safe_error(exc.message, secrets=[secret, *images], texts=[prompt, *texts])
            logger.bind(
                event="model.error", status_code=exc.code, provider_message=detail,
                duration_ms=round((perf_counter() - started) * 1000, 2), **fields,
            ).error("Gemini request failed: HTTP {} — {}", exc.code, detail)
            raise TutorError(f"模型请求失败（HTTP {exc.code}），请检查模型名称、权限、配额或稍后重试。", status_code=exc.code, error_code="provider") from exc
        except (httpx.HTTPError, TimeoutError, ConnectionError) as exc:
            logger.bind(event="model.network_error", exception_type=type(exc).__name__, duration_ms=round((perf_counter() - started) * 1000, 2), **fields).error("Gemini connection failed")
            raise TutorError("模型连接失败或超时，请检查网络后重试。", error_code="network") from exc
        candidates = response.candidates or []
        if not candidates or candidates[0].finish_reason != types.FinishReason.STOP:
            reason = str(candidates[0].finish_reason) if candidates else "NO_CANDIDATE"
            logger.bind(event="model.incomplete", finish_reason=reason, **fields).warning("Gemini response did not complete")
            raise TutorError("模型未正常完成回答（可能被拦截或超过输出限制），本轮未写入历史。")
        answer = (response.text or "").strip()
        if not answer:
            logger.bind(event="model.empty", **fields).warning("Gemini returned empty text")
            raise TutorError("模型没有返回有效文字，本轮未写入历史。")
        usage = response.usage_metadata
        logger.bind(
            event="model.success", duration_ms=round((perf_counter() - started) * 1000, 2),
            output_chars=len(answer), input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None), **fields,
        ).info("Gemini response received")
        return answer

    def close(self) -> None:
        with self._lock:
            if not self._closed and self._owns_client:
                self._client.close()
            self._closed = True
            self._history.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

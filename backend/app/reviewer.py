import re
from dataclasses import dataclass

from .models import utcnow


@dataclass(frozen=True)
class Rule:
    terms: tuple[str, ...]
    severity: str
    category: str
    title: str
    description: str
    recommendation: str
    score: int


RULES = (
    Rule(("unlimited liability", "无限责任"), "critical", "liability", "存在无限责任条款", "责任范围没有明确上限。", "设置明确的责任上限，并排除间接损失。", 45),
    Rule(("automatic renewal", "自动续约"), "medium", "term", "包含自动续约机制", "合同可能在未主动确认时续期。", "增加续约前通知期和便捷的退出机制。", 20),
    Rule(("sole discretion", "自行决定", "单方决定"), "high", "fairness", "单方裁量权过宽", "一方可以在缺少客观标准时单方决定。", "补充客观判断标准和双方协商程序。", 30),
    Rule(("irrevocable", "不可撤销"), "high", "rights", "权利授予不可撤销", "授权缺少可撤回条件。", "限定授权目的、范围、地域和有效期。", 35),
    Rule(("personal data", "个人信息", "个人数据"), "medium", "privacy", "涉及个人数据处理", "数据处理的范围或保护措施可能不清晰。", "明确处理目的、保存期限、安全措施和数据主体权利。", 25),
    Rule(("penalty", "违约金"), "medium", "payment", "存在违约金约定", "违约金计算方式可能导致过高责任。", "确认计算基数和比例合理，并设置最高限额。", 20),
    Rule(("confidential", "保密"), "low", "confidentiality", "保密义务边界需核对", "保密范围、例外或期限可能不完整。", "补充保密例外、披露流程和义务终止期限。", 10),
)


class ReviewProviderError(RuntimeError):
    pass


class PermanentReviewProviderError(ReviewProviderError):
    pass


class TransientReviewProviderError(ReviewProviderError):
    pass


class MockReviewProvider:
    name = "mock"
    model_name = "deterministic-rules-v2"
    prompt_version = "review-v1"

    def review(self, text: str) -> dict:
        if "[[TRANSIENT_FAIL]]" in text:
            raise TransientReviewProviderError("Transient mock provider failure requested by document marker")
        if "[[FAIL]]" in text:
            raise PermanentReviewProviderError("Mock provider failure requested by document marker")

        lowered = text.lower()
        issues: list[dict] = []
        for rule in RULES:
            matched = next((term for term in rule.terms if term.lower() in lowered), None)
            if not matched:
                continue
            issues.append(
                {
                    "category": rule.category,
                    "severity": rule.severity,
                    "title": rule.title,
                    "description": rule.description,
                    "evidence": self._evidence(text, matched),
                    "location": self._location(text, matched),
                    "recommendation": rule.recommendation,
                    "suggested_revision": rule.recommendation,
                }
            )

        score = min(100, sum(rule.score for rule in RULES if any(term.lower() in lowered for term in rule.terms)))
        severities = {issue["severity"] for issue in issues}
        risk_level = (
            "critical"
            if "critical" in severities or score >= 70
            else "high"
            if "high" in severities or score >= 40
            else "medium"
            if "medium" in severities or score >= 15
            else "low"
        )
        summary = (
            f"完成规则化审核，共发现 {len(issues)} 个关注项；整体风险等级为 {risk_level.upper()}。"
            if issues
            else "未发现预设高风险表达。建议仍由专业人员复核关键商业条件。"
        )

        return {
            "overall_risk_level": risk_level,
            "risk_score": score,
            "summary": summary,
            "issues": issues,
            "review_scope": "general",
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "reviewed_at": utcnow().isoformat(),
        }

    @staticmethod
    def _evidence(text: str, term: str) -> str:
        match = re.search(re.escape(term), text, flags=re.IGNORECASE)
        if not match:
            return term
        start = max(0, match.start() - 45)
        end = min(len(text), match.end() + 75)
        excerpt = " ".join(text[start:end].split())
        return f"…{excerpt}…" if start or end < len(text) else excerpt

    @staticmethod
    def _location(text: str, term: str) -> str | None:
        match = re.search(re.escape(term), text, flags=re.IGNORECASE)
        if not match:
            return None
        return f"paragraph {text[:match.start()].count(chr(10)) + 1}"

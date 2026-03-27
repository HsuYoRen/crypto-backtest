from core.sizing.fixed_sizer import FixedSizer
from core.sizing.risk_pct_sizer import RiskPctSizer


class SizerFactory:

    @staticmethod
    def create(name="fixed", **kwargs):
        name = name.lower()

        if name in ("fixed", "fixed_sizer", "simple"):
            return FixedSizer(
                fixed_qty=kwargs.get("fixed_qty", 1),
                leverage=kwargs.get("leverage", 1.0)
            )
        
        elif name in ("risk_pct", "risk", "percent"):
            return RiskPctSizer(
                risk_pct=kwargs.get("risk_pct", 0.1),
                leverage=kwargs.get("leverage", 1.0)
            )

        raise ValueError(f"尚未支援的 Sizer: {name}")

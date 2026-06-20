"""
SENECIO ORACLE — ACT XXVII: Research subpackage
================================================

Institutional research-grade validation + observability layer built
additively on top of the existing oracle pipeline.

ACT-XXVII modules (all STRICT_ADDITIVE — none touch prediction_model /
feature_engineering / signal_generation / verifier):

  Priority 1 — Purged Walk-Forward Validation
    from .purged_cv import PurgedKFold, CombinatorialPurgedCV, run_purged_kfold, run_cpcv

  Priority 2 — Probability Calibration
    from .calibration import (
        PlattCalibrator, IsotonicCalibrator, BetaCalibrator, IdentityCalibrator,
        fit_and_evaluate, brier_score, expected_calibration_error,
        reliability_curve, maximum_calibration_error,
    )

  Priority 3 — Drift Detection
    from .drift_detector import (
        DriftMonitor, PSIDetector, KSDriftDetector,
        PageHinkleyDetector, ADWINDetector, psi_score,
    )

  Priority 4 — Research Metrics
    from .research_metrics import (
        information_coefficient, rolling_information_coefficient,
        feature_stability, prediction_stability,
        rolling_sharpe, rolling_profit_factor, rolling_max_drawdown,
        compute_research_metrics,
    )

  Priority 5 — Explainability
    from .explainability import (
        Explainer, fit_explainer, Attribution, PredictionExplanation,
    )

  Priority 6 — Observability
    from .observability import MetricsRegistry, get_registry, timed

  Coordinator (ties everything together)
    from .coordinator import ResearchCoordinator, ResearchPassReport

Public API:
    coord = ResearchCoordinator()
    coord.load_predictions()
    report = coord.run_full_pass()
"""
from .purged_cv import (
    PurgedKFold,
    PurgedFold,
    CombinatorialPurgedCV,
    CPCVPath,
    FoldResult,
    ValidationReport,
    run_purged_kfold,
    run_cpcv,
)
from .calibration import (
    Calibrator,
    IdentityCalibrator,
    PlattCalibrator,
    IsotonicCalibrator,
    BetaCalibrator,
    CalibrationReport,
    brier_score,
    reliability_curve,
    expected_calibration_error,
    maximum_calibration_error,
    fit_and_evaluate,
)
from .drift_detector import (
    DriftMonitor,
    DriftWarning,
    PSIDetector,
    KSDriftDetector,
    PageHinkleyDetector,
    ADWINDetector,
    psi_score,
)
from .research_metrics import (
    information_coefficient,
    rolling_information_coefficient,
    feature_stability,
    prediction_stability,
    rolling_sharpe,
    rolling_profit_factor,
    rolling_max_drawdown,
    ResearchMetricsReport,
    compute_research_metrics,
)
from .explainability import (
    Explainer,
    fit_explainer,
    Attribution,
    PredictionExplanation,
)
from .observability import (
    MetricSpec,
    DEFAULT_METRIC_SPECS,
    MetricsRegistry,
    get_registry,
    timed,
)
from .coordinator import (
    ResearchCoordinator,
    ResearchPassReport,
)

__all__ = [
    # Priority 1
    "PurgedKFold",
    "PurgedFold",
    "CombinatorialPurgedCV",
    "CPCVPath",
    "FoldResult",
    "ValidationReport",
    "run_purged_kfold",
    "run_cpcv",
    # Priority 2
    "Calibrator",
    "IdentityCalibrator",
    "PlattCalibrator",
    "IsotonicCalibrator",
    "BetaCalibrator",
    "CalibrationReport",
    "brier_score",
    "reliability_curve",
    "expected_calibration_error",
    "maximum_calibration_error",
    "fit_and_evaluate",
    # Priority 3
    "DriftMonitor",
    "DriftWarning",
    "PSIDetector",
    "KSDriftDetector",
    "PageHinkleyDetector",
    "ADWINDetector",
    "psi_score",
    # Priority 4
    "information_coefficient",
    "rolling_information_coefficient",
    "feature_stability",
    "prediction_stability",
    "rolling_sharpe",
    "rolling_profit_factor",
    "rolling_max_drawdown",
    "ResearchMetricsReport",
    "compute_research_metrics",
    # Priority 5
    "Explainer",
    "fit_explainer",
    "Attribution",
    "PredictionExplanation",
    # Priority 6
    "MetricSpec",
    "DEFAULT_METRIC_SPECS",
    "MetricsRegistry",
    "get_registry",
    "timed",
    # Coordinator
    "ResearchCoordinator",
    "ResearchPassReport",
]

VERSION = "ACT-XXVII-research-grade-validation"

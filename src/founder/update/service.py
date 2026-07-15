"""Update application service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import exp, log, sqrt

from founder.selection.contracts import CandidateMembership, CurrentSelectionPointer, SelectionState
from founder.selection.ports import SelectionReadPort
from founder.update.contracts import (
    UPDATE_CONTRACT_VERSION,
    AssetMetricArtifact,
    ClassificationProfile,
    ComparableAssetMetric,
    CurrentUpdatePointer,
    EvaluationProfile,
    MetricSpec,
    PairMetricArtifact,
    PinnedUpdateInput,
    PriceObservation,
    ScreeningClassification,
    SelectionAnalysisManifest,
    SelectionCalendar,
    UpdatePlan,
    UpdateRequest,
    UpdateRunManifest,
    UpdateWorkItem,
    UpdateWorkKind,
)


class UpdateService:
    """Plan Update work from the current Selection read port."""

    def __init__(self, *, selection_read_port: SelectionReadPort | None = None) -> None:
        self._selection_read_port = selection_read_port
        self._current_pointer: CurrentUpdatePointer | None = None

    @staticmethod
    def contract_version() -> str:
        return UPDATE_CONTRACT_VERSION.qualified_name

    def plan_current_selection(self, request: UpdateRequest) -> UpdatePlan:
        pointer = self._current_selection_pointer()
        if pointer.selection_id != request.selection_id:
            raise ValueError("update request does not match the current Selection")
        candidate = self._candidate_membership(pointer.candidate_membership_id)
        if not candidate.listing_ids:
            raise ValueError("cannot plan Update work for an empty Selection")
        pinned = PinnedUpdateInput(
            selection_id=pointer.selection_id,
            candidate_membership_id=pointer.candidate_membership_id,
            final_membership_id=pointer.membership_id,
            refresh_snapshot_id=candidate.catalog_snapshot_id,
        )
        asset_work = tuple(
            UpdateWorkItem(f"asset:{listing_id}", UpdateWorkKind.ASSET_METRIC)
            for listing_id in sorted(candidate.listing_ids)
        )
        finalization: tuple[UpdateWorkItem, ...] = ()
        if pointer.state is SelectionState.PENDING_UPDATE:
            finalization = (
                UpdateWorkItem(
                    "selection:finalize",
                    UpdateWorkKind.SELECTION_FINALIZATION,
                    tuple(item.work_id for item in asset_work),
                ),
            )
        return UpdatePlan(pinned_input=pinned, work_items=(*asset_work, *finalization))

    def publish_manifest(self, manifest: UpdateRunManifest) -> CurrentUpdatePointer:
        if not manifest.published:
            raise ValueError("only published update manifests can become current")
        pointer = CurrentUpdatePointer(run_id=manifest.run_id, plan_id=manifest.plan_id)
        self._current_pointer = pointer
        return pointer

    def current_pointer(self) -> CurrentUpdatePointer | None:
        return self._current_pointer

    def compute_asset_metrics(
        self,
        listing_id: str,
        observations: Sequence[PriceObservation],
        spec: MetricSpec | None = None,
    ) -> AssetMetricArtifact:
        return compute_asset_metric_artifact(listing_id, observations, spec or MetricSpec("asset"))

    def classify_asset(
        self,
        artifact: AssetMetricArtifact,
        profile: ClassificationProfile | None = None,
    ) -> ScreeningClassification:
        return classify_asset_metric_artifact(artifact, profile or ClassificationProfile())

    def build_calendar(
        self,
        *,
        final_membership_id: str,
        returns_by_listing: Mapping[str, Mapping[str, float]],
    ) -> SelectionCalendar:
        return build_selection_calendar(final_membership_id, returns_by_listing)

    def compute_pair_metrics(
        self,
        left_listing_id: str,
        right_listing_id: str,
        left_returns: Mapping[str, float],
        right_returns: Mapping[str, float],
        spec: MetricSpec | None = None,
    ) -> PairMetricArtifact:
        return compute_pair_metric_artifact(
            left_listing_id,
            right_listing_id,
            left_returns,
            right_returns,
            spec or MetricSpec("pair"),
        )

    def build_analysis_manifest(
        self,
        *,
        selection_id: str,
        final_membership_id: str,
        calendar: SelectionCalendar,
        artifact_ids: Sequence[str],
        profile: EvaluationProfile | None = None,
    ) -> SelectionAnalysisManifest:
        selected_profile = profile or EvaluationProfile()
        if len(artifact_ids) > selected_profile.max_members * selected_profile.max_members:
            raise ValueError("analysis exceeds evaluation profile scale limit")
        return SelectionAnalysisManifest(
            selection_id=selection_id,
            final_membership_id=final_membership_id,
            calendar_id=calendar.calendar_id,
            evaluation_profile_id=selected_profile.profile_id,
            artifact_ids=tuple(artifact_ids),
        )

    def _current_selection_pointer(self) -> CurrentSelectionPointer:
        if self._selection_read_port is None:
            raise ValueError("update planning requires a Selection read port")
        pointer = self._selection_read_port.current_pointer()
        if pointer is None:
            raise ValueError("cannot plan Update work without a current Selection")
        if pointer.state in {SelectionState.PAUSED, SelectionState.ARCHIVED, SelectionState.STALE}:
            raise ValueError(f"cannot plan Update work for {pointer.state.value} Selection")
        return pointer

    def _candidate_membership(self, candidate_membership_id: str) -> CandidateMembership:
        if self._selection_read_port is None:
            raise ValueError("update planning requires a Selection read port")
        candidate = self._selection_read_port.candidate_membership(candidate_membership_id)
        if candidate is None:
            raise ValueError("current Selection candidate membership is unavailable")
        return candidate


def compute_asset_metric_artifact(
    listing_id: str,
    observations: Sequence[PriceObservation],
    spec: MetricSpec,
) -> AssetMetricArtifact:
    ordered = sorted(
        (row for row in observations if row.listing_id == listing_id), key=lambda row: row.date
    )
    if len(ordered) < 2:
        return _unavailable_asset_metric(listing_id, spec, "insufficient_history")
    if any(row.adjusted_close <= 0 for row in ordered):
        return _unavailable_asset_metric(listing_id, spec, "invalid_adjusted_close")
    returns = [
        log(current.adjusted_close / previous.adjusted_close)
        for previous, current in zip(ordered, ordered[1:], strict=False)
    ]
    mean_return = sum(returns) / len(returns)
    variance = _sample_variance(returns)
    annualized_volatility = sqrt(variance) * sqrt(spec.annualization_days)
    downside_returns = [min(0.0, item) for item in returns]
    downside_deviation = sqrt(
        sum(item * item for item in downside_returns) / len(downside_returns)
    ) * sqrt(spec.annualization_days)
    annualized_return = mean_return * spec.annualization_days
    losses = sorted((-item for item in returns if item < 0.0), reverse=True)
    tail_count = max(1, int(len(losses) * 0.025)) if losses else 0
    var = losses[tail_count - 1] if tail_count else 0.0
    expected_shortfall = sum(losses[:tail_count]) / tail_count if tail_count else 0.0
    wealth = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for item in returns:
        wealth *= exp(item)
        peak = max(peak, wealth)
        max_drawdown = min(max_drawdown, wealth / peak - 1.0)
    years = max(1.0 / spec.annualization_days, len(returns) / spec.annualization_days)
    cagr = (ordered[-1].adjusted_close / ordered[0].adjusted_close) ** (1.0 / years) - 1.0
    slope, r_squared = _linear_slope_and_r_squared(
        [float(index) for index, _ in enumerate(ordered)],
        [log(row.adjusted_close) for row in ordered],
    )
    return AssetMetricArtifact(
        listing_id=listing_id,
        metric_spec_id=spec.metric_spec_id,
        observation_count=len(returns),
        first_return_date=ordered[1].date,
        last_return_date=ordered[-1].date,
        mean_log_return=mean_return,
        annualized_volatility=annualized_volatility,
        downside_deviation=downside_deviation,
        sharpe_ratio=_ratio(annualized_return, annualized_volatility),
        sortino_ratio=_ratio(annualized_return, downside_deviation),
        expected_shortfall=expected_shortfall,
        var=var,
        max_drawdown=max_drawdown,
        positive_day_ratio=sum(1 for item in returns if item > 0.0) / len(returns),
        cagr=cagr,
        log_price_slope=slope * spec.annualization_days,
        trend_r_squared=r_squared,
    )


def classify_asset_metric_artifact(
    artifact: AssetMetricArtifact,
    profile: ClassificationProfile,
) -> ScreeningClassification:
    if artifact.availability_reason or artifact.observation_count < profile.minimum_observations:
        reason = artifact.availability_reason or "insufficient_history"
        return ScreeningClassification(
            listing_id=artifact.listing_id,
            profile_id=profile.profile_id,
            asset_metric_artifact_id=artifact.artifact_id,
            close_price_path_type="unavailable",
            nav_path_type="unavailable",
            total_return_type="unavailable",
            risk_type="unavailable",
            availability_reason=reason,
        )
    close_path = _path_type(artifact.log_price_slope)
    total_return_type = _total_return_type(artifact)
    risk_type = _worst_risk_band(
        (
            _drawdown_band(artifact.max_drawdown),
            _expected_shortfall_band(artifact.expected_shortfall),
        )
    )
    return ScreeningClassification(
        listing_id=artifact.listing_id,
        profile_id=profile.profile_id,
        asset_metric_artifact_id=artifact.artifact_id,
        close_price_path_type=close_path,
        nav_path_type="unavailable",
        total_return_type=total_return_type,
        risk_type=risk_type,
    )


def build_selection_calendar(
    final_membership_id: str,
    returns_by_listing: Mapping[str, Mapping[str, float]],
) -> SelectionCalendar:
    if not returns_by_listing:
        raise ValueError("selection calendar requires at least one member")
    common_dates: set[str] | None = None
    for listing_returns in returns_by_listing.values():
        dates = set(listing_returns)
        common_dates = dates if common_dates is None else common_dates & dates
    calendar_dates = tuple(sorted(common_dates or set()))
    if not calendar_dates:
        raise ValueError("selection calendar has no common dates")
    return SelectionCalendar(final_membership_id=final_membership_id, dates=calendar_dates)


def compute_comparable_asset_metric(
    listing_id: str,
    calendar: SelectionCalendar,
    returns: Mapping[str, float],
) -> ComparableAssetMetric:
    values = [returns[date] for date in calendar.dates]
    return ComparableAssetMetric(
        listing_id=listing_id,
        calendar_id=calendar.calendar_id,
        mean_return=sum(values) / len(values),
        variance=_sample_variance(values),
    )


def compute_pair_metric_artifact(
    left_listing_id: str,
    right_listing_id: str,
    left_returns: Mapping[str, float],
    right_returns: Mapping[str, float],
    spec: MetricSpec,
) -> PairMetricArtifact:
    left_id, right_id = sorted((left_listing_id, right_listing_id))
    if left_id == right_id:
        raise ValueError("pair metrics require distinct listing ids")
    oriented_left = left_returns if left_listing_id == left_id else right_returns
    oriented_right = right_returns if right_listing_id == right_id else left_returns
    dates = tuple(sorted(set(oriented_left) & set(oriented_right)))
    if len(dates) < 2:
        raise ValueError("pair metrics require at least two common dates")
    left_values = [oriented_left[date] for date in dates]
    right_values = [oriented_right[date] for date in dates]
    covariance = _covariance(left_values, right_values)
    pearson = _ratio(
        covariance, sqrt(_sample_variance(left_values) * _sample_variance(right_values))
    )
    spearman = _pearson(_ranks(left_values), _ranks(right_values))
    return PairMetricArtifact(
        left_listing_id=left_id,
        right_listing_id=right_id,
        metric_spec_id=spec.metric_spec_id,
        observation_count=len(dates),
        first_common_date=dates[0],
        last_common_date=dates[-1],
        covariance=covariance,
        pearson=pearson,
        spearman=spearman,
    )


def _unavailable_asset_metric(
    listing_id: str, spec: MetricSpec, reason: str
) -> AssetMetricArtifact:
    return AssetMetricArtifact(
        listing_id=listing_id,
        metric_spec_id=spec.metric_spec_id,
        observation_count=0,
        first_return_date="",
        last_return_date="",
        mean_log_return=0.0,
        annualized_volatility=0.0,
        downside_deviation=0.0,
        sharpe_ratio=0.0,
        sortino_ratio=0.0,
        expected_shortfall=0.0,
        var=0.0,
        max_drawdown=0.0,
        positive_day_ratio=0.0,
        cagr=0.0,
        log_price_slope=0.0,
        trend_r_squared=0.0,
        availability_reason=reason,
    )


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _sample_variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    return sum((item - mean_value) ** 2 for item in values) / (len(values) - 1)


def _covariance(left: Sequence[float], right: Sequence[float]) -> float:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    return sum(
        (left_item - left_mean) * (right_item - right_mean)
        for left_item, right_item in zip(left, right, strict=True)
    ) / (len(left) - 1)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    return _ratio(_covariance(left, right), sqrt(_sample_variance(left) * _sample_variance(right)))


def _ranks(values: Sequence[float]) -> tuple[float, ...]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    for rank, (_, index) in enumerate(ordered, start=1):
        ranks[index] = float(rank)
    return tuple(ranks)


def _linear_slope_and_r_squared(
    x_values: Sequence[float], y_values: Sequence[float]
) -> tuple[float, float]:
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((item - x_mean) ** 2 for item in x_values)
    if not denominator:
        return (0.0, 0.0)
    slope = (
        sum(
            (x_item - x_mean) * (y_item - y_mean)
            for x_item, y_item in zip(x_values, y_values, strict=True)
        )
        / denominator
    )
    residual_sum = sum(
        (y_item - (y_mean + slope * (x_item - x_mean))) ** 2
        for x_item, y_item in zip(x_values, y_values, strict=True)
    )
    total_sum = sum((item - y_mean) ** 2 for item in y_values)
    return (slope, 1.0 - residual_sum / total_sum if total_sum else 0.0)


def _path_type(slope: float) -> str:
    if slope > 0.02:
        return "growing"
    if slope >= -0.02:
        return "stable"
    if slope > -0.10:
        return "eroding"
    return "strong_decline"


def _total_return_type(artifact: AssetMetricArtifact) -> str:
    if artifact.cagr < -0.02:
        return "negative"
    if artifact.cagr <= 0.02:
        return "sideways"
    if (
        artifact.trend_r_squared >= 0.80
        and artifact.annualized_volatility <= 0.20
        and artifact.max_drawdown >= -0.20
    ):
        return "steadily_growing"
    return "volatile_growing"


def _drawdown_band(drawdown: float) -> str:
    if drawdown >= -0.10:
        return "low"
    if drawdown >= -0.20:
        return "moderate"
    if drawdown >= -0.40:
        return "high"
    return "severe"


def _expected_shortfall_band(expected_shortfall: float) -> str:
    if expected_shortfall <= 0.01:
        return "low"
    if expected_shortfall <= 0.02:
        return "moderate"
    if expected_shortfall <= 0.04:
        return "high"
    return "severe"


def _worst_risk_band(bands: Sequence[str]) -> str:
    order = {"low": 0, "moderate": 1, "high": 2, "severe": 3}
    return max(bands, key=lambda band: order[band])


__all__ = [
    "UpdateService",
    "build_selection_calendar",
    "classify_asset_metric_artifact",
    "compute_asset_metric_artifact",
    "compute_comparable_asset_metric",
    "compute_pair_metric_artifact",
]

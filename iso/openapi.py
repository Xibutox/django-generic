"""One OpenAPI name per choice set of the ISO apps.

Several ISO models share a column name - ``kind``, ``status``,
``category`` - with different choices, and some share one set of
choices under several names (a severity, a rating). drf-spectacular
then guesses names and warns (``drf_spectacular.W001``), which
``check --deploy`` reports. A project gives it these names instead::

    from iso.openapi import ENUM_NAME_OVERRIDES as ISO_ENUMS

    SPECTACULAR_SETTINGS = {
        ...
        "ENUM_NAME_OVERRIDES": {**ISO_ENUMS, ...},
    }

Plain strings, so a settings file imports it before the apps load. A
name whose app is not installed is never looked up.
"""

from __future__ import annotations

ENUM_NAME_OVERRIDES = {
    # Shared by several apps.
    # A severity, a criticality, a risk level: one scale.
    "IsoSeverityEnum": "iso.common.Severity",
    "IsoClassificationEnum": "iso.common.Classification",
    # isms
    "ScopeStatusEnum": "iso.isms.models.Scope.Status",
    "ContextIssueKindEnum": "iso.isms.models.ContextIssue.Kind",
    "ContextIssueCategoryEnum": "iso.isms.models.ContextIssue.Category",
    "ContextIssueEffectEnum": "iso.isms.models.ContextIssue.Effect",
    "InterestedPartyKindEnum": "iso.isms.models.InterestedParty.Kind",
    "ObjectiveDirectionEnum": "iso.isms.models.Objective.Direction",
    "ObjectiveStatusEnum": "iso.isms.models.Objective.Status",
    # A policy and a continuity plan: draft, approved, retired.
    "IsoDocumentStatusEnum": "iso.isms.models.Policy.Status",
    "ContactKindEnum": "iso.isms.models.Contact.Kind",
    "ManagementReviewStatusEnum": "iso.isms.models.ManagementReview.Status",
    "ReviewActionStatusEnum": "iso.isms.models.ReviewAction.Status",
    # assets
    "AssetKindEnum": "iso.assets.models.Asset.Kind",
    "AssetRatingEnum": "iso.assets.models.RATINGS",
    "AssetStatusEnum": "iso.assets.models.Asset.Status",
    "AssetMaintenanceKindEnum": "iso.assets.models.Maintenance.Kind",
    "DisposalMethodEnum": "iso.assets.models.Disposal.Method",
    # compliance
    "ControlThemeEnum": "iso.compliance.models.Control.Theme",
    "ControlStatusEnum": "iso.compliance.models.Control.Status",
    "ObligationKindEnum": "iso.compliance.models.Obligation.Kind",
    "ObligationStatusEnum": "iso.compliance.models.Obligation.Status",
    # risks
    "RiskCategoryEnum": "iso.risks.models.Risk.Category",
    "RiskLikelihoodEnum": "iso.risks.models.SCALE",
    "RiskImpactEnum": "iso.risks.models.IMPACTS",
    "RiskTreatmentEnum": "iso.risks.models.Risk.Treatment",
    "RiskStatusEnum": "iso.risks.models.Risk.Status",
    "TreatmentActionStatusEnum": "iso.risks.models.TreatmentAction.Status",
    # suppliers
    "IsoSupplierStatusEnum": "iso.suppliers.models.Supplier.Status",
    "SupplierDataAccessEnum": "iso.suppliers.models.Supplier.DataAccess",
    "AgreementKindEnum": "iso.suppliers.models.Agreement.Kind",
    "AssessmentMethodEnum": "iso.suppliers.models.Assessment.Method",
    "AssessmentResultEnum": "iso.suppliers.models.Assessment.Result",
    # incidents
    "IncidentCategoryEnum": "iso.incidents.models.Incident.Category",
    "IncidentStatusEnum": "iso.incidents.models.Incident.Status",
    "IncidentUpdateKindEnum": "iso.incidents.models.IncidentUpdate.Kind",
    # vulnerabilities
    "VulnerabilitySourceEnum": (
        "iso.vulnerabilities.models.Vulnerability.Source"
    ),
    "VulnerabilityStatusEnum": (
        "iso.vulnerabilities.models.Vulnerability.Status"
    ),
    # changes
    "ChangeKindEnum": "iso.changes.models.ChangeRequest.Kind",
    "ChangeCategoryEnum": "iso.changes.models.ChangeRequest.Category",
    "ChangeRiskEnum": "iso.changes.models.ChangeRequest.Risk",
    "ChangeStatusEnum": "iso.changes.models.ChangeRequest.Status",
    # continuity
    "ExerciseKindEnum": "iso.continuity.models.Exercise.Kind",
    "ExerciseResultEnum": "iso.continuity.models.Exercise.Result",
    # audits
    "AuditKindEnum": "iso.audits.models.Audit.Kind",
    "AuditStatusEnum": "iso.audits.models.Audit.Status",
    "NonconformitySourceEnum": "iso.audits.models.Nonconformity.Source",
    "NonconformityGradeEnum": "iso.audits.models.Nonconformity.Grade",
    "NonconformityStatusEnum": "iso.audits.models.Nonconformity.Status",
    "CorrectiveActionKindEnum": "iso.audits.models.CorrectiveAction.Kind",
    "CorrectiveActionStatusEnum": (
        "iso.audits.models.CorrectiveAction.Status"
    ),
    # people
    "CourseTopicEnum": "iso.people.models.Course.Topic",
    "EmploymentEnum": "iso.people.models.PersonnelFile.Employment",
    "PersonnelFileStatusEnum": "iso.people.models.PersonnelFile.Status",
    # access_reviews
    "AccessReviewScopeEnum": "iso.access_reviews.models.AccessReview.Scope",
    "AccessReviewStatusEnum": "iso.access_reviews.models.AccessReview.Status",
    "AccessDecisionEnum": (
        "iso.access_reviews.models.AccessReviewItem.Decision"
    ),
}

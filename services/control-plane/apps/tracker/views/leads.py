import csv
from io import StringIO
import json
from typing import Any

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.jobs.models.jobs import JobPostingSource
from apps.jobs.services.fx_rates import (
    get_request_fx_snapshot,
    resolve_display_currency,
)
from apps.tracker.models import ApplicationLead
from apps.tracker.serializers.leads import ApplicationLeadSerializer

EXPORT_COLUMNS: tuple[str, ...] = (
    "uuid",
    "job_title",
    "company_name",
    "ats_source",
    "status",
    "priority",
    "next_action_at",
    "applied_at",
    "last_activity_at",
    "apply_url",
    "notes",
    "created_at",
)

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in _FORMULA_PREFIXES:
        return f"'{text}"
    return text


class CSVExportRenderer(BaseRenderer):
    media_type = "text/csv"
    format = "csv"
    charset = "utf-8"

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: dict[str, Any] | None = None,
    ) -> bytes:
        if data is None:
            return b""
        # Guard DRF error dicts (401/403/400) so content negotiation never crashes into 500
        if not isinstance(data, list):
            return json.dumps(data, ensure_ascii=False).encode(self.charset)

        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(EXPORT_COLUMNS)
        for row in data:
            if not isinstance(row, dict):
                continue
            writer.writerow([sanitize_csv_cell(row.get(col)) for col in EXPORT_COLUMNS])
        return buffer.getvalue().encode(self.charset)


def _format_iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_lead_export_row(lead: ApplicationLead) -> dict[str, Any]:
    return {
        "uuid": str(lead.uuid),
        "job_title": lead.job_posting.title,
        "company_name": lead.job_posting.company_name,
        "ats_source": lead.job_posting.ats_source,
        "status": lead.status,
        "priority": lead.priority,
        "next_action_at": _format_iso(lead.next_action_at),
        "applied_at": _format_iso(lead.applied_at),
        "last_activity_at": _format_iso(lead.last_activity_at),
        "apply_url": lead.job_posting.apply_url,
        "notes": lead.notes,
        "created_at": _format_iso(lead.created_at),
    }


class ApplicationLeadViewSet(viewsets.ModelViewSet):
    queryset = ApplicationLead.objects.none()
    serializer_class = ApplicationLeadSerializer
    lookup_field = "uuid"
    filterset_fields = ["status", "priority", "resume_profile"]
    ordering_fields = [
        "modified_at",
        "last_activity_at",
        "applied_at",
        "next_action_at",
        "created_at",
    ]
    ordering = ["-modified_at"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action in ("list", "retrieve", "create", "update", "partial_update"):
            fx_snapshot = get_request_fx_snapshot(self.request)
            context["fx_snapshot"] = fx_snapshot
            context["display_currency"] = resolve_display_currency(
                self.request, fx_snapshot
            )
        return context

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ApplicationLead.objects.none()
        return (
            ApplicationLead.objects.filter(user=self.request.user)
            .select_related("job_posting", "resume_profile")
            .prefetch_related(
                Prefetch(
                    "job_posting__sources",
                    queryset=JobPostingSource.objects.filter(is_deleted=False).order_by(
                        "-is_primary", "first_seen_at"
                    ),
                    to_attr="prefetched_sources",
                )
            )
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="export",
        renderer_classes=[JSONRenderer, CSVExportRenderer],
    )
    def export(self, request: Request) -> Response:
        leads = self.filter_queryset(self.get_queryset())
        rows = [_serialize_lead_export_row(lead) for lead in leads]
        ext = (
            "csv"
            if getattr(request.accepted_renderer, "format", "") == "csv"
            else "json"
        )
        date_stamp = timezone.now().strftime("%Y-%m-%d")
        filename = f"vektryn-leads-{date_stamp}.{ext}"
        return Response(
            rows,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

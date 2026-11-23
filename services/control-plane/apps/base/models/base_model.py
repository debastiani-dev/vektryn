import uuid
from typing import Any, Optional

from django.db import models
from django.utils.translation import gettext_lazy as _
from enum import StrEnum


def enum_choices(enum_cls: type[StrEnum]) -> list[tuple[str, str]]:
    return [(member.value, member.name.replace("_", " ").title()) for member in enum_cls]


class BaseQuerySet(models.QuerySet):
    def delete(self, destroy: bool = False) -> tuple[int, dict[str, int]]:
        if not destroy:
            updated = self.update(is_deleted=True)
            return updated, {self.model._meta.label: updated}
        return super().delete()

    def soft_delete(self) -> int:
        return self.update(is_deleted=True)

    def restore(self) -> int:
        return self.update(is_deleted=False)


class BaseManager(models.Manager):
    def get_queryset(self) -> BaseQuerySet:
        return BaseQuerySet(self.model, using=self._db).filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    def get_queryset(self) -> BaseQuerySet:
        return BaseQuerySet(self.model, using=self._db)


class TimestampsOnlyBaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))
    modified_at = models.DateTimeField(auto_now=True, verbose_name=_("Modified at"))

    class Meta:
        abstract = True


class BaseModel(TimestampsOnlyBaseModel):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        primary_key=True,
        verbose_name=_("uuid"),
    )
    is_deleted = models.BooleanField(default=False, db_index=True)

    objects = BaseManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = [*update_fields, "modified_at"]
        super().save(*args, **kwargs)

    def delete(
        self,
        using: Optional[str] = None,
        keep_parents: bool = False,
        destroy: bool = False,
    ) -> Any:
        if not destroy:
            self.soft_delete()
            return 1, {self._meta.label: 1}
        return super().delete(using=using, keep_parents=keep_parents)

    def soft_delete(self) -> None:
        self.is_deleted = True
        self.save(update_fields=["is_deleted"])

    def restore(self) -> None:
        self.is_deleted = False
        self.save(update_fields=["is_deleted"])

    @property
    def deleted_date(self):
        return self.modified_at if self.is_deleted else None
# Generated for Feature Spec #3: Hybrid Keyword + Semantic Search

import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations

SEARCH_VECTOR_EXPR = """
    setweight(to_tsvector('english', coalesce({prefix}title, '')), 'A')
    || setweight(to_tsvector('english', coalesce({prefix}company_name, '')), 'B')
    || setweight(
        jsonb_to_tsvector(
            'english',
            coalesce({prefix}tech_stack, '[]'::jsonb),
            '["string"]'
        ),
        'B'
    )
    || setweight(to_tsvector('english', coalesce({prefix}description_clean, '')), 'C')
"""

CREATE_TRIGGER_AND_BACKFILL_SQL = f"""
CREATE OR REPLACE FUNCTION jobs_jobposting_update_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector := {SEARCH_VECTOR_EXPR.format(prefix="NEW.")};
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_jobs_jobposting_search_vector ON jobs_jobposting;
CREATE TRIGGER trg_jobs_jobposting_search_vector
BEFORE INSERT OR UPDATE OF title, company_name, tech_stack, description_clean
ON jobs_jobposting
FOR EACH ROW
EXECUTE FUNCTION jobs_jobposting_update_search_vector();

UPDATE jobs_jobposting
SET search_vector = {SEARCH_VECTOR_EXPR.format(prefix="")};
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_jobs_jobposting_search_vector ON jobs_jobposting;
DROP FUNCTION IF EXISTS jobs_jobposting_update_search_vector();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0003_alter_jobposting_apply_url_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobposting",
            name="search_vector",
            field=django.contrib.postgres.search.SearchVectorField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.RunSQL(
            sql=CREATE_TRIGGER_AND_BACKFILL_SQL,
            reverse_sql=DROP_TRIGGER_SQL,
        ),
        migrations.AddIndex(
            model_name="jobposting",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_vector"],
                name="gin_job_posting_search_vector",
            ),
        ),
    ]

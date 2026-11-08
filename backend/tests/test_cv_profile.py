"""CVProfile.skills: names only, capped, de-duplicated, and backward compatible with old rows."""

from app.schemas.analysis import MAX_CV_SKILLS, CVProfile
from app.services.llm import to_strict_schema

BASE = {"name": None, "education": [], "projects": [], "experience": [], "certifications": []}


def test_skills_are_plain_strings_in_llm_schema() -> None:
    schema = to_strict_schema(CVProfile)
    assert schema["properties"]["skills"]["items"] == {"type": "string"}


def test_old_stored_shape_still_loads() -> None:
    p = CVProfile.model_validate(
        BASE | {"skills": [{"name": "Python", "evidence_sentence": "Python, SQL"}, "SQL"]}
    )
    assert p.skills == ["Python", "SQL"]


def test_skills_capped_and_deduplicated() -> None:
    many = [f"Skill{i}" for i in range(80)] + ["python", "Python", "  ", ""]
    p = CVProfile.model_validate(BASE | {"skills": ["Python", *many]})
    assert len(p.skills) == MAX_CV_SKILLS
    assert p.skills[0] == "Python"
    assert len({s.lower() for s in p.skills}) == len(p.skills)

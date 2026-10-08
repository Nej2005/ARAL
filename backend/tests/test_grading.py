from app.services.grading import grade, normalize_answer, term_matches


def test_normalize_answer():
    assert normalize_answer("  The Calvin-Cycle! ") == "calvin cycle"
    assert normalize_answer("An ATP") == "atp"
    assert normalize_answer("Résumé") == "resume"


def test_mcq_and_true_false():
    assert grade("mcq", "c2", [], "c2") == (True, None)
    assert grade("mcq", "c2", [], "c1") == (False, None)
    assert grade("true_false", "false", [], "FALSE") == (True, None)
    assert grade("true_false", "false", [], "yes") == (False, None)


def test_identification_exact_alias_typo_and_threshold():
    acc = ["Central Processing Unit", "CPU"]
    assert grade("identification", "Central Processing Unit", acc, "cpu") == (True, None)
    assert grade("identification", "Central Processing Unit", acc, "the central processing unit.") == (True, None)
    assert grade("identification", "Photosynthesis", ["Photosynthesis"], "Photosynthesys") == (True, "typo_tolerated")
    assert grade("identification", "Photosynthesis", ["Photosynthesis"], "Photo") == (False, None)
    assert grade("identification", "Photosynthesis", ["Photosynthesis"], "") == (False, None)
    # threshold edge: ratio of "stomata" vs "stomato" is ~86 -> wrong at 90, right at 85
    assert grade("identification", "Stomata", ["Stomata"], "stomato", threshold=90)[0] is False
    assert grade("identification", "Stomata", ["Stomata"], "stomato", threshold=85)[0] is True


def test_term_matches():
    assert term_matches("osmosis", "Osmosis")
    assert term_matches("osmossis", "Osmosis")
    assert not term_matches("diffusion", "Osmosis")

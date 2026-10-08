from app.services.fidelity import (
    BLANK,
    LessonIndex,
    Rejection,
    ValidatedItem,
    blank_term,
    check_false_statement,
    check_fill_in_stem,
    check_identification,
    check_rationale,
    check_true_statement,
    dedupe_items,
    find_span,
    rationale_fallback,
    topic_key,
    validate_item,
)

PAGE = (
    "Photosynthesis\n"
    "• Photosynthesis – the process by which green plants use sunlight to synthesize food from carbon dioxide and water.\n"
    "• Chlorophyll – the green pigment in chloroplasts that absorbs light energy, mostly in the blue\n"
    "  and red wavelengths.\n"
    "• The chloroplast is the organelle where photosynthesis takes place.\n"
)


def test_find_span_exact_and_whitespace_insensitive():
    assert find_span(PAGE, "The chloroplast is the organelle") is not None
    s, e = find_span(PAGE, "absorbs light energy, mostly in the blue and red wavelengths.")
    assert "absorbs light energy" in PAGE[s:e] and "wavelengths" in PAGE[s:e]


def test_find_span_fuzzy_snaps_to_real_text():
    # One typo in the model's quote: still located, and the returned text is the page's own.
    s, e = find_span(PAGE, "the green pigmant in chloroplasts that absorbs light energy")
    assert PAGE[s:e].startswith("the green pigment")


def test_find_span_rejects_paraphrase():
    assert find_span(PAGE, "Plants make food using sunlight and water in a process called photosynthesis") is None


def test_validate_item_keeps_verbatim_quote():
    raw = {"kind": "definition", "term": "Chlorophyll", "aliases": [],
           "body": "the green pigment in chloroplasts that absorbs light energy, mostly in the blue and red wavelengths",
           "source_quote": "Chlorophyll – the green pigment in chloroplasts that absorbs light energy, mostly in the blue and red wavelengths.",
           "topic": "Photosynthesis"}
    v = validate_item(raw, PAGE, 1)
    assert isinstance(v, ValidatedItem)
    assert PAGE[v.quote_start:v.quote_end] == v.source_quote
    assert v.source_quote.startswith("Chlorophyll – the green pigment")
    assert v.topic_key == "photosynthesis"


def test_validate_item_drops_paraphrased_body():
    raw = {"kind": "fact", "term": "chloroplast", "body": "Photosynthesis happens inside the chloroplast organelle",
           "source_quote": "The chloroplast is the organelle where photosynthesis takes place."}
    v = validate_item(raw, PAGE, 1)
    assert isinstance(v, Rejection) and v.reason == "body_not_in_quote"


def test_validate_item_drops_quote_not_in_page():
    raw = {"kind": "fact", "term": "mitochondria", "body": "The mitochondria is the powerhouse",
           "source_quote": "The mitochondria is the powerhouse of the cell."}
    assert isinstance(validate_item(raw, PAGE, 1), Rejection)


def test_dedupe_merges_same_term_similar_body():
    a = ValidatedItem("definition", 1, "ATP", ["adenosine triphosphate"], "the main energy-carrying molecule of the cell",
                      "ATP – the main energy-carrying molecule of the cell", 0, 10, None)
    b = ValidatedItem("definition", 2, "atp", [], "the main energy carrying molecule of the cell.",
                      "ATP – the main energy carrying molecule of the cell.", 0, 10, None)
    c = ValidatedItem("definition", 2, "ATP synthase", [], "an enzyme", "ATP synthase – an enzyme", 0, 5, None)
    kept, merged = dedupe_items([a, b, c], existing=[("Krebs cycle", "a series of reactions", [])])
    assert [k.term for k in kept] == ["ATP", "ATP synthase"]
    assert merged == {}
    kept2, merged2 = dedupe_items([b], existing=[("ATP", "the main energy-carrying molecule of the cell", [])])
    assert kept2 == [] and 0 in merged2


def test_topic_key_groups_continuations():
    assert topic_key("Cell Structure (cont.)") == topic_key("Cell Structure") == "cell structure"
    assert topic_key("Cell Structure – Part 2") == "cell structure"
    assert topic_key("Cell Structure (continued)") == "cell structure"
    assert topic_key(None) is None


def test_blank_term_and_identification_check():
    body = "the process by which green plants use sunlight to synthesize food"
    assert blank_term(body, "sunlight") == f"the process by which green plants use {BLANK} to synthesize food"
    assert check_identification(body, body, "Photosynthesis")
    assert check_identification(blank_term("Photosynthesis is the process", "Photosynthesis"),
                                "Photosynthesis is the process", "Photosynthesis")
    assert not check_identification("the way plants make food", body, "Photosynthesis")


def test_fill_in_stem_check():
    quote = "The chloroplast is the organelle where photosynthesis takes place."
    assert check_fill_in_stem(f"The {BLANK} is the organelle where photosynthesis takes place.", quote, "chloroplast")
    assert not check_fill_in_stem(f"The {BLANK} is where photosynthesis happens.", quote, "chloroplast")
    assert not check_fill_in_stem(f"{BLANK} and {BLANK}", quote, "chloroplast")


def test_true_statement_check():
    quote = "• The chloroplast is the organelle where photosynthesis takes place."
    assert check_true_statement("The chloroplast is the organelle where photosynthesis takes place.", quote, "x")
    assert not check_true_statement("The chloroplast is where photosynthesis happens.", quote, "x")


def test_false_statement_exactly_one_edit():
    t = "The light-dependent reactions take place in the thylakoid membranes of the chloroplast."
    f = "The light-dependent reactions take place in the stroma of the chloroplast."
    assert check_false_statement(f, t, "thylakoid membranes", "stroma")
    # two edits -> rejected
    f2 = "The light-independent reactions take place in the stroma of the chloroplast."
    assert not check_false_statement(f2, t, "thylakoid membranes", "stroma")
    # span not in the statement -> rejected
    assert not check_false_statement(f, t, "mitochondria", "stroma")
    # nothing changed -> rejected
    assert not check_false_statement(t, t, "thylakoid membranes", "thylakoid membranes")


def test_rationale_checks_and_fallback():
    index = LessonIndex.build([type("I", (), {"term": "Stomata", "body": "small pores on the underside of a leaf",
                                               "source_quote": "Stomata – small pores on the underside of a leaf", "aliases": []})()])
    assert check_rationale("Stomata are the leaf's \"small pores\" for gas exchange.", index.text_norm)
    assert not check_rationale("", index.text_norm)
    assert not check_rationale(" ".join(["word"] * 41), index.text_norm)
    assert not check_rationale('The lesson says "stomata are in the roots".', index.text_norm)
    # T/F replacement presented as true -> rejected; presented as wrong -> allowed
    assert not check_rationale("The reactions happen in the stroma.", index.text_norm, forbidden_as_true="stroma")
    assert check_rationale("They do not happen in the stroma; the lesson says thylakoid membranes.", index.text_norm,
                           forbidden_as_true="stroma")
    assert rationale_fallback("• Stomata – small pores\n  on the underside of a leaf") == \
        "The lesson states: 'Stomata – small pores on the underside of a leaf'"

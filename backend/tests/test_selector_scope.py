import random
from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.models import Document
from app.services.generation.selector import availability, select, split_count, spread_order
from app.services.scope import filter_items, normalize_scope, validate_scope


def item(i, doc="d1", page=1, kind="fact", topic_key=None):
    return SimpleNamespace(id=f"i{i}", document_id=doc, page_no=page, kind=kind, topic_key=topic_key, term=f"t{i}")


def test_split_count_even_with_remainder_to_first():
    assert split_count(10, ["mcq", "true_false", "identification"]) == {"mcq": 4, "true_false": 3, "identification": 3}
    assert split_count(2, ["identification", "mcq"]) == {"identification": 1, "mcq": 1}


def test_select_identification_only_definitions_and_shortfall_redistributed():
    items = [item(1, kind="definition"), item(2, kind="definition")] + [item(i) for i in range(3, 13)]
    picked = select(items, ["identification", "mcq", "true_false"], 9, random.Random(1))
    assert len(picked) == 9
    ident = [it for t, it in picked if t == "identification"]
    assert all(it.kind == "definition" for it in ident) and len(ident) == 2  # only 2 definitions exist
    assert len({it.id for _, it in picked}) == 9  # no item used twice


def test_select_never_exceeds_available():
    items = [item(i) for i in range(1, 4)]
    assert len(select(items, ["mcq"], 10, random.Random(0))) == 3
    assert select([], ["mcq"], 5) == []


def test_spread_order_round_robins_across_pages():
    items = [item(i, page=1) for i in range(1, 6)] + [item(i, page=2) for i in range(6, 11)] + [item(11, doc="d2", page=1)]
    order = spread_order(items, random.Random(3))
    first3 = {(o.document_id, o.page_no) for o in order[:3]}
    assert len(first3) == 3


def test_availability_numbers():
    items = [item(1, kind="definition"), item(2), item(3)]
    used = {"i2"}
    av = availability(items[:2], items, used, ["mcq"])
    assert av.total_items == 3 and av.used_items == 1 and av.unused_items == 1 and av.unused_outside_scope == 1
    assert av.max_count_for_types == 1
    assert availability(items, items, used, ["identification"]).max_count_for_types == 1
    assert availability(items, items, used, []).max_count_for_types == 0


def test_scope_filter_documents_pages_topics():
    items = [item(1, "d1", 2, topic_key="cells"), item(2, "d1", 7, topic_key="cells"), item(3, "d2", 1, topic_key="energy")]
    assert normalize_scope({"documents": [], "topics": []}) is None
    sc = {"documents": [{"document_id": "d1", "pages": [[1, 5]]}]}
    assert [i.id for i in filter_items(items, sc)] == ["i1"]
    assert [i.id for i in filter_items(items, {"topics": ["Energy"]})] == ["i3"]
    assert [i.id for i in filter_items(items, {"documents": [{"document_id": "d1"}], "topics": ["Cells (cont.)"]})] == ["i1", "i2"]
    assert len(filter_items(items, None)) == 3


def test_validate_scope_errors():
    docs = [Document(id="d1", filename="a.pdf", file_type="pdf", storage_path="", sha256="x", page_count=10)]
    with pytest.raises(AppError) as e:
        validate_scope({"documents": [{"document_id": "zzz"}]}, docs, set())
    assert e.value.code == "INVALID_SCOPE"
    with pytest.raises(AppError):
        validate_scope({"documents": [{"document_id": "d1", "pages": [[3, 40]]}]}, docs, set())
    with pytest.raises(AppError):
        validate_scope({"topics": ["Nope"]}, docs, {"cells"})
    assert validate_scope({"topics": ["Cells"]}, docs, {"cells"}) == {"topics": ["Cells"]}

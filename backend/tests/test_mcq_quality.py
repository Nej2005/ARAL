"""Multiple-choice questions must not give the answer away (cases taken from a real lesson)."""

from __future__ import annotations

import random
from types import SimpleNamespace

from app.services.fidelity import BLANK, LessonIndex, mask_terms, mentions, poor_option, strip_term_prefix, too_close
from app.services.generation import Draft
from app.services.generation.identification import build_identification
from app.services.generation.multiple_choice import finish_mcq, meaning_text, prepare_mcq

DOC = SimpleNamespace(id="d1", filename="Module 4.pptx", page_label=lambda n: f"slide {n}")


def item(id, term, body, quote=None, kind="definition", aliases=(), topic="permissions", page=1):
    return SimpleNamespace(id=id, term=term, body=body, source_quote=quote or body, kind=kind, aliases=list(aliases),
                           topic=topic, topic_key=topic, document_id="d1", page_no=page)


PERMS = [
    item("read", "Read", "Read–Allows groups or users to read and execute files."),
    item("rw", "Read/Write", "Read/Write–Allows groups or users to read, execute, delete, and modify the contents of files, as well as add and delete subfolders."),
    item("change", "Change", "Change–Allows groups or users to read, execute, delete, and modify the contents of files and subfolders."),
    item("full", "Full Control", "Full Control–Allows groups or users to read, execute, delete, and modify files and modify share permissions."),
    item("owner", "Owner", "Owner – the user that created the file or folder, who can always change its permissions."),
]
FS = [
    item("refs", "ReFS", "ReFS – Resilient File System", topic="filesystems"),
    item("ntfs", "NTFS", "NTFS - New Technology File System", topic="filesystems"),
    item("fat", "FAT32", "FAT32 – File Allocation Table 32 (for local storage and removable media)", topic="filesystems"),
    item("exfat", "exFAT", "exFAT – Extended File Allocation Table, used for large removable drives", topic="filesystems"),
]
QUOTAS = [
    item("hard", "hard quota", "prevent users from storing files after a limit has been reached",
         quote="Folder quotas can be configured to prevent users from storing files after a limit has been reached (called a hard quota) or allow the limit to be surpassed (called a soft quota).", topic="quotas"),
    item("soft", "soft quota", "allow the limit to be surpassed", quote="or allow the limit to be surpassed (called a soft quota).", topic="quotas"),
    item("ntfsq", "NTFS user quotas", "NTFS user quotas are not enabled on each filesystem by default.", kind="fact", topic="quotas"),
    item("userq", "User quotas", "User quotas – limit the space a single user can consume on a volume.", topic="quotas"),
    item("folderq", "Folder quotas", "Folder quotas – limit the space consumed by a folder on the filesystem.", topic="quotas"),
    item("templ", "Quota Templates", "Quota Templates – store quota settings that simplify creating new quota entries.", topic="quotas"),
    item("num", "16777216", "The maximum number of entries is 16777216.", kind="fact", topic="quotas"),
]
DFS = [
    item("ns", "DFS Namespaces", "DFS Namespaces provides a central location from which users can access the different shared folders within their organization.", kind="fact", topic="dfs"),
    item("dfs", "Distributed File System", "Distributed File System – an optional component that adds functionality for accessing shared folders.", aliases=["DFS"], topic="dfs"),
    item("repl", "DFS Replication", "DFS Replication – keeps folder contents the same on several servers.", topic="dfs"),
    item("hub", "Hub and spoke", "Hub and spoke – forces replication to occur via a central member.", topic="dfs"),
    item("mesh", "Full mesh", "Full mesh – every member replicates with every other member.", topic="dfs"),
    item("smb", "SMB", "Originally developed by IBM, SMB is the default file sharing protocol used by Windows systems.",
         quote="SMB (Server Message Block) – Originally developed by IBM, SMB is the default file sharing protocol used by Windows systems.",
         aliases=["Server Message Block"], topic="dfs"),
]
OWNERSHIP = [
    item("own", "owner", "Each folder and file on a system must have an owner, which, by default, is the user that created the file.", kind="fact", topic="ownership"),
]
ALL = PERMS + FS + QUOTAS + DFS + OWNERSHIP
BY_ID = {i.id: i for i in ALL}


def build(it, fmt=None, picks=None, seed=1):
    """Build a question; with `fmt`, retry other shuffles until that format is used (it may switch to avoid a hint)."""
    for s in range(seed, seed + 60):
        rng = random.Random(s)
        d = prepare_mcq(Draft(ref="q1", type="mcq", item=it, doc=DOC), ALL, rng)
        if d.failed or (fmt and d.mcq_format != fmt):
            continue
        finish_mcq(d, picks or [], [], BY_ID, {"d1": DOC}, LessonIndex.build(ALL), rng)
        if not d.failed:
            return d
    raise AssertionError(f"no {fmt or 'any'} question could be built for {it.term!r}")


def options(d):
    return [c["text"] for c in d.choices]


# ---------------------------------------------------------------- helpers


def test_strip_term_prefix_and_meaning_text():
    assert strip_term_prefix("Read–Allows groups or users to read and execute files.", ["Read"]) == "Allows groups or users to read and execute files."
    assert strip_term_prefix("NTFS - New Technology File System", ["NTFS"]) == "New Technology File System"
    assert strip_term_prefix("SMB (Server Message Block) – Originally developed", ["SMB"]) == "Originally developed"
    assert meaning_text(BY_ID["smb"]) == f"Originally developed by IBM, {BLANK} is the default file sharing protocol used by Windows systems."
    assert meaning_text(BY_ID["refs"]) == "Resilient File System"


def test_mask_terms_hides_every_mention_and_the_article():
    q = BY_ID["smb"].source_quote
    out = mask_terms(q, ["SMB", "Server Message Block"])
    assert "SMB" not in out and "Server Message Block" not in out
    assert out.startswith(BLANK + " – Originally")  # "SMB (Server Message Block)" folds into one blank
    assert mask_terms("must have an owner, which", ["owner"]) == f"must have a(n) {BLANK}, which"
    assert mask_terms("Stomata let gas in; each stoma is a pore", ["Stomata", "stoma"]).count(BLANK) == 2


def test_implied_aliases_and_case_rules():
    from app.services.fidelity import implied_aliases
    assert implied_aliases("Server Message Block (SMB)") == ["Server Message Block", "SMB"]
    assert implied_aliases("Enable access-based enumeration") == ["access-based enumeration"]
    assert implied_aliases("Read") == []
    assert mask_terms("Allows users to read files", ["Read"]) == "Allows users to read files"  # verb kept
    assert mask_terms("assigned to the owner of the folder", ["Owner"]) == f"assigned to the {BLANK} of the folder"
    assert mask_terms("Originally developed by IBM, SMB is", ["Server Message Block (SMB)", "SMB"]).count("SMB") == 0


def test_too_close_and_poor_options():
    assert too_close("NTFS user quotas", "User quotas")
    assert too_close("DFS Namespaces", "Distributed File System")  # DFS = Distributed File System
    assert too_close("Owner", "owner")
    assert not too_close("DFS Namespaces", "DFS Replication")
    assert not too_close("hard quota", "soft quota")
    assert not too_close("Read", "Read/Write")
    assert poor_option("16777216") and poor_option("or allow the limit to be surpassed")
    assert not poor_option("Full Control")


# ---------------------------------------------------------------- questions


def test_term_meaning_options_never_show_their_own_terms():
    for it in PERMS + FS:
        d = build(it, fmt="term_meaning")
        names = [n for c in d.choices if c["source_item_id"] for n in [BY_ID[c["source_item_id"]].term]]
        for c in d.choices:
            assert not mentions(c["text"], [it.term]), (it.term, c["text"])
            src = BY_ID[c["source_item_id"]]
            assert not mentions(c["text"], [src.term]), (src.term, c["text"])
        assert d.choices[0]["text"][0].isupper()
        assert len(names) == 4


def test_fill_in_stem_hides_answer_and_aliases():
    d = build(BY_ID["smb"], fmt="fill_in")
    assert BLANK in d.prompt and not mentions(d.prompt, ["SMB", "Server Message Block"])
    d = build(BY_ID["own"], fmt="fill_in")
    assert "a(n) " + BLANK in d.prompt and " an " + BLANK not in d.prompt
    assert options(d)[0] == "Owner"  # capitalized like every other option
    # capitalized, except names that have their own casing (exFAT)
    assert all(o[0].isupper() or o[0].isdigit() or any(ch.isupper() for ch in o.split()[0][1:]) for o in options(d))


def test_no_option_could_also_be_right_or_is_ruled_out_by_the_stem():
    for it in ALL:
        if it.kind != "definition" and not it.term:
            continue
        try:
            d = build(it, fmt="fill_in")
        except AssertionError:
            continue  # no fill-in possible for this item
        answer = it.term
        for o in options(d)[1:]:
            assert not too_close(answer, o), (answer, o)
            assert not mentions(d.prompt, [o]), (d.prompt, o)
            assert not poor_option(o), o
    # the concrete cases from the live exam
    hard = build(BY_ID["hard"], fmt="fill_in")
    assert "Soft quota" not in options(hard)  # the stem says "(called a soft quota)"
    ntfsq = build(BY_ID["ntfsq"])  # whichever format is hint-free
    assert "User quotas" not in options(ntfsq)
    ns = build(BY_ID["ns"], fmt="fill_in")
    assert "Distributed File System" not in options(ns)
    assert "16777216" not in options(build(BY_ID["folderq"]))  # whichever format is hint-free


def test_gemini_picks_outside_the_safe_list_are_ignored():
    d = build(BY_ID["ntfsq"], picks=["userq", "num", "ntfsq"])
    assert "User quotas" not in options(d) and "16777216" not in options(d) and len(set(options(d))) == 4


def test_identification_prompt_hides_the_term():
    for it in PERMS + FS + [BY_ID["smb"]]:
        d = build_identification(Draft(ref="q", type="identification", item=it, doc=DOC))
        assert not d.failed, (it.term, d.prompt)
        assert not mentions(d.prompt, [it.term, *it.aliases]), d.prompt
    d = build_identification(Draft(ref="q", type="identification", item=BY_ID["read"], doc=DOC))
    assert d.prompt == "Allows groups or users to read and execute files."


def test_identical_definitions_are_never_offered_together():
    change = item("chg", "Change", "Change - Allows groups or users to read, execute, delete, and modify the contents of files, as well as add and delete subfolders.", topic="adv")
    rw = item("rw2", "Read/Write", "Read/Write - Allows groups or users to read, execute, delete, and modify the contents of files, as well as add and delete subfolders.", topic="smb")
    pool = ALL + [change, rw]
    for s in range(20):
        d = prepare_mcq(Draft(ref="q", type="mcq", item=change, doc=DOC), pool, random.Random(s))
        if d.failed or d.mcq_format != "fill_in":
            continue
        assert "rw2" not in d.candidate_ids


def test_everyday_domain_words_count_as_echoes():
    from app.services.generation.multiple_choice import content_words
    assert {"user", "quota"} <= content_words("User quotas")
    assert "folder" in content_words("limit the space consumed by a folder")


def test_one_set_never_holds_two_terms_with_the_same_definition():
    from app.services.generation.exam_builder import _one_per_meaning
    change = item("chg", "Change", "Change - Allows groups or users to read, execute, delete, and modify files.")
    rw = item("rw2", "Read/Write", "Read/Write - Allows groups or users to read, execute, delete, and modify files.")
    other = item("oth", "Other", "Other - Something entirely different that is still a definition.")
    kept, spare = _one_per_meaning([("mcq", change), ("mcq", rw)], [other])
    assert [it.id for _, it in kept] == ["chg", "oth"] and spare == []
    kept, _ = _one_per_meaning([("mcq", change), ("mcq", rw)], [])
    assert [it.id for _, it in kept] == ["chg"]


def test_stems_with_too_little_to_go_on_are_not_used():
    from app.services.generation.multiple_choice import enough_words
    assert not enough_words(f"{BLANK} - {BLANK} apply (see Table 5-2)")
    assert enough_words(f"{BLANK} - contains information used to audit the access to the resource")


def test_best_effort_picks_the_least_hinting_options():
    from app.services.generation.multiple_choice import choose_distractors, hint_penalty

    correct = "Search service for files"
    ordered = [("a", "Network share"), ("b", "Backup copy"), ("c", "Quota template"), ("d", "Disk service list")]
    echo = {"service"}
    assert choose_distractors(correct, ordered, echo) is None  # 'service' is in one wrong option only
    trio = choose_distractors(correct, ordered, echo, best_effort=True)
    assert trio and "d" in [i for i, _ in trio]  # the one option that also says 'service' is kept
    assert hint_penalty(correct, [t for _, t in trio], echo) == 1


def test_all_items_identification_twins_accept_either_name():
    from types import SimpleNamespace

    from app.services.generation import Draft
    from app.services.generation.exam_builder import _accept_twin_names, _twins

    body = "Allows groups or users to read, execute, delete, and modify files."
    a = SimpleNamespace(id="a", term="Change", aliases=[], body=body, kind="definition")
    b = SimpleNamespace(id="b", term="Read/Write", aliases=[], body=body, kind="definition")
    c = SimpleNamespace(id="c", term="Read", aliases=[], body="Allows groups or users to read and execute files.",
                        kind="definition")
    twins = _twins([("identification", a), ("identification", b), ("identification", c)])
    assert set(twins) == {"a", "b"}
    d = Draft(ref="q1", type="identification", item=a, doc=None)
    d.accepted_answers = ["Change"]
    _accept_twin_names([d], twins)
    assert d.accepted_answers == ["Change", "Read/Write"]

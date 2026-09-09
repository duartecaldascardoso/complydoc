"""Choosing a subset of a large folder without skewing what the reader sees."""

from __future__ import annotations

from pathlib import Path

from complydoc.sampling import sample_files


def folder(pdfs: int = 90, sheets: int = 9, images: int = 1) -> list[Path]:
    return (
        [Path(f"invoice_{i:03d}.pdf") for i in range(pdfs)]
        + [Path(f"ledger_{i:03d}.xlsx") for i in range(sheets)]
        + [Path(f"scan_{i:03d}.png") for i in range(images)]
    )


def test_a_sample_is_the_size_it_was_asked_for():
    for limit in (1, 2, 3, 10, 50, 99):
        assert len(sample_files(folder(), limit)) == limit


def test_asking_for_more_than_exists_returns_everything():
    files = folder()
    assert sample_files(files, 500) == files
    assert sample_files(files, len(files)) == files


def test_the_same_folder_samples_the_same_way_twice():
    """No seed to record, so two runs of one folder stay comparable."""
    assert sample_files(folder(), 25) == sample_files(folder(), 25)


def test_file_types_keep_their_share_of_the_folder():
    """A 90/9/1 folder must not sample as 100% of whatever sorts first."""
    chosen = sample_files(folder(), 20)
    counts = {suffix: sum(1 for p in chosen if p.suffix == suffix) for suffix in (".pdf", ".xlsx")}
    assert 16 <= counts[".pdf"] <= 19
    assert counts[".xlsx"] >= 1


def test_a_rare_file_type_still_appears():
    """One spreadsheet among ten thousand PDFs is exactly what someone needs to see."""
    files = [Path(f"{i:05d}.pdf") for i in range(10_000)] + [Path("odd.xlsx")]
    chosen = sample_files(files, 50)
    assert Path("odd.xlsx") in chosen


def test_too_few_places_to_go_round_does_not_invent_them():
    """Below one place per type, the sample is still the size requested."""
    files = [Path("a.pdf"), Path("b.xlsx"), Path("c.png"), Path("d.docx")]
    assert len(sample_files(files, 2)) == 2


def test_the_sample_keeps_the_folder_order():
    chosen = sample_files(folder(), 15)
    assert chosen == sorted(chosen, key=folder().index)


def test_a_sample_spans_the_folder_rather_than_its_first_few():
    """Taking the first N would mean auditing January and calling it the year."""
    files = [Path(f"{i:03d}.pdf") for i in range(100)]
    chosen = sample_files(files, 10)
    assert chosen[0] == files[0]
    assert chosen[-1].stem > "080"

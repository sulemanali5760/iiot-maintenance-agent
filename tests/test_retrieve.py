from iiot_agent.retrieve import Retriever


def test_bearing_vibration_ranked_first():
    retriever = Retriever()
    result = retriever.search("vibration bearing wear", 3)
    assert result[0][1] == "Vibration and bearing wear"
    assert len(result) == 3
    assert result == retriever.search("vibration bearing wear", 3)


def test_subheadings_and_empty_manual():
    assert Retriever("# Empty").search("bearing") == []
    assert [r[1] for r in Retriever("## One\nBearing.\n### Two\nPressure.").search("pressure")] == ["Two", "One"]

import pytest

from mwcp.graph import GraphFormatError, read_metis, write_kamis_solution


def test_weighted_with_comments_and_isolated(data_dir):
    g = read_metis(data_dir / "k4_heavy_triangle.graph")
    assert g.n == 8 and g.m == 10
    assert g.weights == [1, 1, 1, 1, 10, 10, 10, 25]
    assert g.adj[7] == set()
    assert g.clique_violation([4, 5, 6]) is None
    assert g.clique_violation([3, 4, 5]) is not None
    assert g.weight_of([4, 5, 6]) == 30


def test_unweighted_default_weights(tmp_path):
    p = tmp_path / "u.graph"
    p.write_text("3 2\n2\n1 3\n2\n")
    g = read_metis(p)
    assert g.weights == [1, 1, 1] and g.m == 2


def test_edge_weights_ignored(tmp_path):
    p = tmp_path / "e.graph"
    p.write_text("2 1 11\n5 2 99\n7 1 99\n")
    g = read_metis(p)
    assert g.weights == [5, 7] and g.adj[0] == {1}


def test_asymmetric_input_is_symmetrized(tmp_path):
    p = tmp_path / "a.graph"
    p.write_text("3 2\n2 3\n\n\n")
    g = read_metis(p)
    assert g.adj[1] == {0} and g.adj[2] == {0}


@pytest.mark.parametrize("text", ["", "3\n", "2 1\n2\n", "2 1\n3\n1\n"])
def test_malformed(tmp_path, text):
    p = tmp_path / "bad.graph"
    p.write_text(text)
    with pytest.raises(GraphFormatError):
        read_metis(p)


def test_kamis_solution(tmp_path):
    p = tmp_path / "s.sol"
    write_kamis_solution(4, [1, 3], p)
    assert p.read_text() == "0\n1\n0\n1\n"

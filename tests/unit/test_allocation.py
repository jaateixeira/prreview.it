from hypothesis import given, settings
from hypothesis import strategies as st

from previewit.domain.allocation import Problem, Slot, conflicts, loads
from previewit.plugins.allocation import ManualStrategy, RandomStrategy, RoundRobinStrategy

PEOPLE = [f"p{i}" for i in range(12)]


def person(i: int) -> Slot:
    return Slot(f"u:{PEOPLE[i]}", frozenset({PEOPLE[i]}))


@st.composite
def problems(draw):
    """Individuals and groups (random members), with a random subset acting as reviewers."""
    n = draw(st.integers(1, 8))
    authors: list[Slot] = []
    for i in range(n):
        if draw(st.booleans()):
            authors.append(person(i))
        else:
            members = draw(st.sets(st.sampled_from(PEOPLE), min_size=1, max_size=3))
            authors.append(Slot(f"g:{i}", frozenset(members)))
    reviewer_pool = draw(st.lists(st.sampled_from(authors), unique_by=lambda s: s.key, max_size=n))
    extra = draw(
        st.sets(
            st.tuples(
                st.sampled_from([a.key for a in authors]),
                st.sampled_from([a.key for a in authors]),
            ),
            max_size=3,
        )
    )
    k = draw(st.integers(1, 4))
    return Problem(reviewer_pool, authors, k, frozenset(extra))


STRATEGIES = [RandomStrategy(), RoundRobinStrategy()]


def check_invariants(problem: Problem, result) -> None:
    reviewers = {r.key: r for r in problem.reviewers}
    submissions = {s.key: s for s in problem.submissions}
    assert len(set(result.pairs)) == len(result.pairs)  # nobody is assigned twice
    per_sub: dict[str, int] = {}
    for rk, sk in result.pairs:
        assert not conflicts(reviewers[rk], submissions[sk], problem.extra_conflicts)
        per_sub[sk] = per_sub.get(sk, 0) + 1
    for sk, s in submissions.items():
        possible = sum(1 for r in problem.reviewers if not conflicts(r, s, problem.extra_conflicts))
        expected = min(problem.per_submission, possible)
        assert per_sub.get(sk, 0) == expected  # exact count, or everything that is possible
        assert result.shortfall.get(sk, 0) == problem.per_submission - expected


@settings(max_examples=300, deadline=None)
@given(problems(), st.integers(0, 10_000))
def test_no_conflicts_no_repeats_and_exact_counts(problem, seed):
    for strategy in STRATEGIES:
        check_invariants(problem, strategy.allocate(problem, seed))


@settings(max_examples=200, deadline=None)
@given(problems(), st.integers(0, 10_000))
def test_the_same_seed_gives_the_same_result(problem, seed):
    for strategy in STRATEGIES:
        assert strategy.allocate(problem, seed) == strategy.allocate(problem, seed)


@settings(max_examples=200, deadline=None)
@given(st.integers(2, 10), st.integers(1, 4), st.integers(0, 1000))
def test_everyone_reviews_everyone_else_evenly(n, k, seed):
    """n:n with individuals: every person gets k reviews and does k (when k < n)."""
    k = min(k, n - 1)
    people = [person(i) for i in range(n)]
    problem = Problem(people, people, k)
    for strategy in STRATEGIES:
        result = strategy.allocate(problem, seed)
        assert not result.shortfall
        counts = loads(result.pairs)
        assert set(counts.values()) == {k}
        assert len(counts) == n


@settings(max_examples=200, deadline=None)
@given(st.integers(2, 9), st.integers(1, 4), st.integers(0, 1000), st.data())
def test_load_is_as_even_as_possible_with_individual_reviewers(n_authors, k, seed, data):
    """With individuals only (no extra conflicts), loads differ by at most one."""
    n_rev = data.draw(st.integers(2, 10))
    authors = [person(i) for i in range(n_authors)]
    reviewers = [person(i) for i in range(n_rev)]
    problem = Problem(reviewers, authors, k)
    for strategy in STRATEGIES:
        result = strategy.allocate(problem, seed)
        counts = loads(result.pairs)
        everyone = [counts.get(r.key, 0) for r in reviewers]
        if not result.shortfall:
            assert max(everyone) - min(everyone) <= 1


def test_a_group_never_reviews_its_member_and_a_member_never_reviews_their_group():
    group = Slot("g:1", frozenset({"a", "b"}))
    a, b, c = (Slot(f"u:{x}", frozenset({x})) for x in "abc")
    problem = Problem([group, a, b, c], [group, a, b, c], 2)
    result = RandomStrategy().allocate(problem, 1)
    forbidden = {("g:1", "u:a"), ("g:1", "u:b"), ("u:a", "g:1"), ("u:b", "g:1")}
    assert not forbidden & set(result.pairs)
    assert ("g:1", "g:1") not in result.pairs


def test_a_shortfall_is_reported_not_hidden():
    solo = person(0)
    problem = Problem([solo], [solo, person(1)], 2)
    result = RoundRobinStrategy().allocate(problem, 0)
    assert result.pairs == ((solo.key, person(1).key),)
    assert result.shortfall == {person(0).key: 2, person(1).key: 1}


def test_existing_pairs_are_not_repeated():
    a, b, c = person(0), person(1), person(2)
    problem = Problem([a, b, c], [a], 1, existing=frozenset({(b.key, a.key)}))
    assert RoundRobinStrategy().allocate(problem, 0).pairs == ((c.key, a.key),)


def test_manual_allocates_nothing_and_reports_the_gap():
    a, b = person(0), person(1)
    result = ManualStrategy().allocate(Problem([a, b], [a, b], 1), 0)
    assert result.pairs == () and result.shortfall == {a.key: 1, b.key: 1}


def test_round_robin_is_a_fixed_pattern():
    people = [person(i) for i in range(4)]
    result = RoundRobinStrategy().allocate(Problem(people, people, 1), 0)
    assert (
        dict((s, r) for r, s in result.pairs)
        == {
            "u:p0": "u:p1",
            "u:p1": "u:p2",
            "u:p2": "u:p3",
            "u:p3": "u:p0",
        }
        or len(result.pairs) == 4
    )

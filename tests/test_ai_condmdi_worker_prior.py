"""The CondMDI request contract for ``skip_timesteps`` (M9, S1-S3).

M6 L23/L25: rows not covered by the observation mask drift toward a
degenerate prior (arm splay) when the gap is wider than the dense-capture
track. The prepared remedy seeds the diffusion with the capture prior and
starts sampling partway down the chain — the vendored ``p_sample_loop``
already takes ``skip_timesteps``/``init_image``, so the worker contract
pinned here is: parse and validate the optional field, and never sample from
pure noise while claiming a prior. Pinned at the helper level; the real GPU
path is measured by the M9 T3 probe (S6).
"""

from __future__ import annotations

import pytest

from aimation_actor.adapters.ai import condmdi_worker as W

_NUM_TIMESTEPS = 1000  # vendored config: steps=1000, no respacing


def _prior() -> object:
    """An opaque prior; identity is what the contract carries through."""
    return object()


def _init(raw: object, num: int = _NUM_TIMESTEPS, prior: object | None = None) -> tuple:
    return W._CondMDIEngine.__new__(W._CondMDIEngine)._prior_init(
        raw, num, prior if prior is not None else _prior()
    )


def test_a_request_without_the_field_samples_exactly_like_today() -> None:
    """skip absent, None or 0: no prior init, no skipped steps."""
    assert _init({}.get("skip_timesteps")) == (0, None)
    assert _init(None) == (0, None)
    assert _init(0) == (0, None)


def test_a_positive_skip_inits_with_the_prior_at_that_noise_level() -> None:
    """skip=k, prior p: the call plan is (k, p) — the fill passes both to
    ``p_sample_loop`` unchanged, and the vendored loop noises ``p`` at
    timestep ``num_timesteps - k - 1`` by itself."""
    prior = _prior()
    assert _init(500, prior=prior) == (500, prior)
    assert _init("500", prior=prior) == (500, prior)


def test_a_skip_beyond_the_chain_is_refused() -> None:
    """S3: 1000 timesteps; skipping all of them would return the prior
    unnoised and undenoised — nonsense the contract refuses."""
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    with pytest.raises(W._RequestError, match="beyond"):
        engine._prior_init(1000, _NUM_TIMESTEPS, _prior())
    with pytest.raises(W._RequestError, match="beyond"):
        engine._prior_init(1001, _NUM_TIMESTEPS, _prior())


def test_a_negative_skip_is_refused() -> None:
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    with pytest.raises(W._RequestError, match="negative"):
        engine._prior_init(-1, _NUM_TIMESTEPS, _prior())


def test_non_integer_garbage_is_refused_not_raised_raw() -> None:
    """A string that is not an integer must surface as the typed per-request
    error, not as a bare ``ValueError`` escaping the protocol."""
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    with pytest.raises(W._RequestError, match="integer"):
        engine._prior_init("noise", _NUM_TIMESTEPS, _prior())

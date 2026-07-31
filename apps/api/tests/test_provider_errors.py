import time
import unittest

from ai.errors import (
    ProviderBadGatewayError,
    ProviderErrorCode,
    ProviderRuntimeError,
    ProviderTimeoutError,
    provider_error_payload,
    provider_failure_code,
)
from ai.runtime.util import remaining_seconds


class ProviderErrorPayloadTests(unittest.TestCase):
    def test_runtime_error_payload_uses_own_code_retryable_and_phase(self):
        exc = ProviderRuntimeError(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "boom", "codex", retryable=True, phase="idle")
        payload = provider_error_payload(exc)
        self.assertEqual(payload, {
            "error": ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
            "code": ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
            "provider": "codex",
            "message": "boom",
            "retryable": True,
            "phase": "idle",
        })

    def test_timeout_error_payload_forces_provider_timeout_code_and_retryable(self):
        exc = ProviderTimeoutError("timed out", phase="first_delta", provider="claude")
        payload = provider_error_payload(exc)
        self.assertEqual(payload, {
            "error": ProviderErrorCode.PROVIDER_TIMEOUT,
            "code": ProviderErrorCode.PROVIDER_TIMEOUT,
            "provider": "claude",
            "message": "timed out",
            "retryable": True,
            "phase": "first_delta",
        })

    def test_bad_gateway_error_payload_has_no_phase_field(self):
        exc = ProviderBadGatewayError("upstream failure", provider="claude")
        payload = provider_error_payload(exc)
        self.assertEqual(payload, {
            "error": ProviderErrorCode.PROVIDER_BAD_GATEWAY,
            "code": ProviderErrorCode.PROVIDER_BAD_GATEWAY,
            "provider": "claude",
            "message": "upstream failure",
            "retryable": True,
        })
        self.assertNotIn("phase", payload)

    def test_phase_omitted_when_falsy(self):
        exc = ProviderRuntimeError(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "boom", "codex")
        payload = provider_error_payload(exc)
        self.assertNotIn("phase", payload)

    def test_fallback_provider_used_only_when_exception_provider_is_missing(self):
        with_provider = ProviderBadGatewayError("upstream failure", provider="codex")
        self.assertEqual(provider_error_payload(with_provider, fallback_provider="claude")["provider"], "codex")

        without_provider = ProviderBadGatewayError("upstream failure", provider=None)
        self.assertEqual(provider_error_payload(without_provider, fallback_provider="claude")["provider"], "claude")


class ProviderFailureCodeTests(unittest.TestCase):
    def test_timeout_error_maps_to_provider_timeout(self):
        exc = ProviderTimeoutError("timed out", provider="codex")
        self.assertEqual(provider_failure_code(exc), ProviderErrorCode.PROVIDER_TIMEOUT)

    def test_runtime_error_maps_to_its_own_code(self):
        exc = ProviderRuntimeError(ProviderErrorCode.PROVIDER_AUTH_REQUIRED, "boom", "codex")
        self.assertEqual(provider_failure_code(exc), ProviderErrorCode.PROVIDER_AUTH_REQUIRED)

    def test_unknown_exception_maps_to_bad_gateway(self):
        self.assertEqual(provider_failure_code(RuntimeError("boom")), ProviderErrorCode.PROVIDER_BAD_GATEWAY)


class RemainingSecondsTests(unittest.TestCase):
    def test_future_deadline_returns_positive_remaining_time(self):
        deadline = time.monotonic() + 10
        self.assertGreater(remaining_seconds(deadline), 9)

    def test_past_deadline_floors_to_minimum(self):
        deadline = time.monotonic() - 10
        self.assertEqual(remaining_seconds(deadline), 0.001)

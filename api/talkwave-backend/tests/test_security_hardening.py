"""Regression tests for security-hardening changes.

Covers the cryptographic / input-validation primitives introduced during the
security audit:

* WS media-connection tickets (HMAC signed, TTL-bound, tuple-bound).
* SSRF URL validation (block loopback / private / metadata targets).
* MySQL read-only query enforcement (block DML/DDL/stacked statements).

These are pure-logic checks with no external dependencies so they run fast in
CI and guard against regressions that would silently re-open the vulnerability.
"""

import time

import pytest

from api.services.integrations.composio_service import DatabaseService
from api.services.security import ssrf
from api.services.security.ws_ticket import generate_ws_ticket, verify_ws_ticket


# ---------------------------------------------------------------------------
# WS ticket
# ---------------------------------------------------------------------------

class TestWsTicket:
    def test_valid_ticket_verifies(self):
        ticket = generate_ws_ticket(1, 2, 3)
        assert verify_ws_ticket(ticket, 1, 2, 3) is True

    def test_ticket_bound_to_tuple(self):
        ticket = generate_ws_ticket(1, 2, 3)
        # Any change to the (workflow_id, user_id, workflow_run_id) tuple fails.
        assert verify_ws_ticket(ticket, 9, 2, 3) is False
        assert verify_ws_ticket(ticket, 1, 9, 3) is False
        assert verify_ws_ticket(ticket, 1, 2, 9) is False

    def test_missing_ticket_rejected(self):
        assert verify_ws_ticket(None, 1, 2, 3) is False
        assert verify_ws_ticket("", 1, 2, 3) is False

    def test_malformed_ticket_rejected(self):
        assert verify_ws_ticket("garbage", 1, 2, 3) is False
        assert verify_ws_ticket("not.a.valid.ticket", 1, 2, 3) is False

    def test_expired_ticket_rejected(self):
        ticket = generate_ws_ticket(1, 2, 3, ttl_seconds=-1)
        assert verify_ws_ticket(ticket, 1, 2, 3) is False

    def test_tampered_signature_rejected(self):
        # A far-future expiry with a bogus signature must still be rejected.
        forged = f"{int(time.time()) + 999}.AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        assert verify_ws_ticket(forged, 1, 2, 3) is False


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

class TestSSRFBlockedIPs:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "0.0.0.0",
            "10.0.0.5",
            "192.168.1.1",
            "172.16.0.1",
            "169.254.169.254",  # cloud metadata endpoint
            "::1",
            "not-an-ip",
        ],
    )
    def test_blocked_ips(self, ip):
        assert ssrf.ip_is_blocked(ip) is True

    @pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
    def test_public_ips_allowed(self, ip):
        assert ssrf.ip_is_blocked(ip) is False


class TestSSRFValidateUrl:
    @pytest.mark.asyncio
    async def test_non_http_scheme_rejected(self):
        assert await ssrf.validate_public_url("file:///etc/passwd") is False
        assert await ssrf.validate_public_url("gopher://x") is False

    @pytest.mark.asyncio
    async def test_no_host_rejected(self):
        assert await ssrf.validate_public_url("http://") is False

    @pytest.mark.asyncio
    async def test_literal_private_ip_rejected(self):
        assert await ssrf.validate_public_url("http://127.0.0.1/admin") is False
        assert (
            await ssrf.validate_public_url("http://169.254.169.254/latest/meta-data")
            is False
        )

    @pytest.mark.asyncio
    async def test_literal_public_ip_allowed(self):
        assert await ssrf.validate_public_url("https://8.8.8.8/") is True

    @pytest.mark.asyncio
    async def test_assert_raises_on_unsafe(self):
        with pytest.raises(ssrf.UnsafeURLError):
            await ssrf.assert_public_url("http://127.0.0.1")


# ---------------------------------------------------------------------------
# MySQL read-only enforcement
# ---------------------------------------------------------------------------

class TestMySQLReadOnly:
    @pytest.mark.parametrize(
        "query",
        [
            "SELECT * FROM users",
            "select id, name from customers where id = %s",
            "WITH t AS (SELECT 1) SELECT * FROM t",
            "SELECT 1;",  # single trailing semicolon allowed
        ],
    )
    def test_allowed_read_queries(self, query):
        assert DatabaseService._is_read_only_query(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "INSERT INTO users VALUES (1)",
            "UPDATE users SET name = 'x'",
            "DELETE FROM users",
            "DROP TABLE users",
            "TRUNCATE users",
            "ALTER TABLE users ADD COLUMN x INT",
            "SELECT * FROM users; DROP TABLE users",  # stacked
            "SELECT * INTO OUTFILE '/tmp/x' FROM users",
            "SELECT LOAD_FILE('/etc/passwd')",
            "CALL some_proc()",
            "",
            "   ",
        ],
    )
    def test_rejected_queries(self, query):
        assert DatabaseService._is_read_only_query(query) is False

"""Redaction is the security boundary of the collector. Every credential shape we
know about gets a test, and so does every readable value we must not destroy."""

import pytest

from flockit.redact import (
    REDACTED,
    SESSION_FIELDS,
    normalize_repo,
    normalize_task_ref,
    redact_session,
    scrub,
)

# Fake credentials, assembled at runtime so secret scanners do not flag this file.
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY"
GH_PAT = "ghp_" + "1234567890abcdefghijABCDEFGHIJ123456"
GH_FINE = "github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789"
GL_PAT = "glpat-" + "xxxxxxxxxxxxxxxxxxxx"
SLACK = "xoxb-" + "123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"
STRIPE = "sk_live_" + "51H8abcdefghijklmnopqrstuv"
OPENAI = "sk-proj-" + "abcdefghijklmnopqrstuvwxyz0123456789ABCD"
ANTHROPIC = "sk-ant-" + "api03-abcdefghijklmnopqrstuvwxyz0123456789-ABCDEFG"
GOOGLE = "AIza" + "SyA1234567890abcdefghijklmnopqrstuvw"
NPM = "npm_" + "abcdefghijklmnopqrstuvwxyz0123456789"
HF = "hf_" + "abcdefghijklmnopqrstuvwxyzABCDEFGH"
JWT = "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0" + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
FLK = "flk_" + "AbCdEfGhIjKlMnOpQrStUvWx"


class TestApiKeys:
    @pytest.mark.parametrize(
        "secret",
        [AWS_KEY, GH_PAT, GH_FINE, GL_PAT, SLACK, STRIPE, OPENAI, ANTHROPIC, GOOGLE, NPM, HF, FLK],
        ids=["aws", "github-classic", "github-fine-grained", "gitlab", "slack", "stripe", "openai",
             "anthropic", "google", "npm", "huggingface", "flockit"],
    )
    def test_known_key_formats_are_removed(self, secret):
        out = scrub("before %s after" % secret)
        assert secret not in out
        assert REDACTED in out
        assert out.startswith("before ") and out.endswith(" after")

    def test_key_embedded_in_branch_name(self):
        out = scrub("fix/rotate-" + GH_PAT)
        assert GH_PAT not in out
        assert out.startswith("fix/rotate-")

    def test_multiple_keys_in_one_string(self):
        out = scrub("%s and %s" % (AWS_KEY, STRIPE))
        assert AWS_KEY not in out and STRIPE not in out
        assert out.count(REDACTED) == 2

    def test_private_key_block(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nabc\n-----END RSA PRIVATE KEY-----"
        assert scrub("key: " + pem) == "key: " + REDACTED

    def test_truncated_private_key_block(self):
        out = scrub("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk")
        assert "b3BlbnNzaC1rZXk" not in out

    def test_unknown_high_entropy_blob(self):
        blob = "Zq8Xv2Lm9Kp4Rt7Wn3Bc6Hd1Fg5Js0Ya"
        assert scrub("value " + blob) == "value " + REDACTED

    def test_long_hex_secret(self):
        hexsecret = "a3f5" * 12
        assert scrub(hexsecret) == REDACTED


class TestTokens:
    def test_bearer_header(self):
        out = scrub("Authorization: Bearer abc.def-ghi_jkl123")
        assert "abc.def-ghi_jkl123" not in out

    def test_basic_auth_header(self):
        out = scrub("Authorization: Basic dXNlcjpwYXNzd29yZA==")
        assert "dXNlcjpwYXNzd29yZA" not in out

    def test_jwt(self):
        out = scrub("token " + JWT)
        assert JWT not in out

    @pytest.mark.parametrize("param", ["token", "access_token", "api_key", "apikey", "key", "secret",
                                       "signature", "X-Amz-Signature", "password", "code"])
    def test_sensitive_query_parameters(self, param):
        url = "https://api.example.com/v1/items?page=2&%s=s3cr3tvalue&sort=asc" % param
        out = scrub(url)
        assert "s3cr3tvalue" not in out
        assert "page=2" in out and "sort=asc" in out

    def test_slack_webhook(self):
        url = "https://hooks.slack.com/" + "services/T00000000/B00000000/" + "X" * 24
        assert "XXXXXXXXXXXX" not in scrub(url)


class TestConnectionStrings:
    @pytest.mark.parametrize(
        "dsn,secret",
        [
            ("postgres://admin:hunter2@db.internal:5432/app", "hunter2"),
            ("postgresql+asyncpg://svc:p%40ss@10.0.0.4/app", "p%40ss"),
            ("mysql://root:rootpw@localhost:3306/shop", "rootpw"),
            ("mongodb+srv://user:mongopass@cluster0.abcd.mongodb.net/db", "mongopass"),
            ("redis://:redispass@cache:6379/0", "redispass"),
            ("amqp://guest:guestpw@rabbit:5672/", "guestpw"),
            ("https://deploy:" + GH_PAT + "@github.com/acme/api.git", GH_PAT),
        ],
    )
    def test_password_removed_host_kept(self, dsn, secret):
        out = scrub("url=" + dsn)
        assert secret not in out
        assert REDACTED in out

    def test_token_only_userinfo(self):
        out = scrub("https://x" + "a" * 30 + "@github.com/acme/api")
        assert "a" * 30 not in out
        assert "github.com/acme/api" in out


class TestEnvVars:
    @pytest.mark.parametrize(
        "line,secret",
        [
            ("DATABASE_URL=postgres://u:p@h/db", "postgres://u:p@h/db"),
            ("export AWS_SECRET_ACCESS_KEY=" + AWS_SECRET, AWS_SECRET),
            ("STRIPE_API_KEY='abc123def456'", "abc123def456"),
            ('GITHUB_TOKEN="plainvalue99"', "plainvalue99"),
            ("DB_PASSWORD: correcthorse", "correcthorse"),
            ("client_secret=shhh-value", "shhh-value"),
            ("SENTRY_DSN=https://abc@o1.ingest.sentry.io/1", "https://abc@o1.ingest.sentry.io/1"),
            ("REDIS_CONNECTION_STRING=redis://cache", "redis://cache"),
            ("my_private_key => topsecretvalue", "topsecretvalue"),
        ],
    )
    def test_secret_named_assignments(self, line, secret):
        out = scrub(line)
        assert secret not in out
        assert REDACTED in out

    def test_non_secret_assignments_survive(self):
        assert scrub("NODE_ENV=production PORT=8080") == "NODE_ENV=production PORT=8080"


class TestReadableValuesSurvive:
    @pytest.mark.parametrize(
        "text",
        [
            "main",
            "feature/ENG-123-add-login",
            "feature/improve-the-session-list-filters-and-sorting-on-mobile",
            "gilad/refactor_ingest_pipeline_for_multi_tenant_support",
            "release/2026.09.19",
            "claude-opus-5",
            "claude-sonnet-5[1m]",
            "https://github.com/acme/api/issues/42",
            "feature/ENG-123-add-login-and-OAuth2-refresh-flow",
            "fix/handle-utf8-in-CSVExportService-for-large-files",
            "dependabot/npm_and_yarn/web/vite-8.3.0",
            "users/gilad.levy/PLAT-431-flaky-e2e-on-safari-17",
            "claude-haiku-4-5-20251001",
        ],
    )
    def test_unchanged(self, text):
        assert scrub(text) == text

    def test_empty(self):
        assert scrub("") == ""


class TestRepoNormalisation:
    @pytest.mark.parametrize(
        "remote,expected",
        [
            ("https://github.com/acme/api.git", "github.com/acme/api"),
            ("https://user:" + GH_PAT + "@github.com/acme/api.git", "github.com/acme/api"),
            ("https://oauth2:" + GL_PAT + "@gitlab.example.com/group/sub/repo.git", "gitlab.example.com/group/sub/repo"),
            ("git@github.com:acme/api.git", "github.com/acme/api"),
            ("ssh://git@github.com/acme/api.git", "github.com/acme/api"),
            ("GitHub.com:Acme/API", "github.com/Acme/API"),
            ("/Users/gilad/code/secret-client-project", "secret-client-project"),
            ("/home/dev/work/api/", "api"),
        ],
    )
    def test_normalise(self, remote, expected):
        assert normalize_repo(remote) == expected

    def test_local_path_never_includes_username(self):
        assert "gilad" not in (normalize_repo("/Users/gilad/code/api") or "")

    def test_rejects_garbage(self):
        assert normalize_repo("") is None
        assert normalize_repo(None) is None
        assert normalize_repo(42) is None


class TestTaskRef:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("ENG-123", "ENG-123"),
            ("#42", "#42"),
            ("https://github.com/acme/api/issues/42", "https://github.com/acme/api/issues/42"),
            ("https://acme.atlassian.net/browse/ENG-9?token=abc#comment", "https://acme.atlassian.net/browse/ENG-9"),
            ("https://user:pw@tracker.example.com/tickets/9", "https://tracker.example.com/tickets/9"),
            ("https://gitlab.acme.dev/grp/sub/api/-/issues/7", "https://gitlab.acme.dev/grp/sub/api/-/issues/7"),
            ("https://linear.app/acme/issue/ENG-5/login-is-broken", "https://linear.app/acme/issue/ENG-5"),
            ("https://github.com/acme/api/pull/9/files", "https://github.com/acme/api/pull/9"),
        ],
    )
    def test_accepted(self, raw, expected):
        assert normalize_task_ref(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "fix the login bug", "eng-123", "ftp://x/y", "", None, "javascript:alert(1)",
            "https://tracker.example.com/t/9",  # not a recognised ticket path
            "https://example.com/some/random/page",
            "https://jira.acme.com/browse/" + AWS_KEY,  # a secret where the ticket id should be
        ],
    )
    def test_rejected(self, raw):
        assert normalize_task_ref(raw) is None


class TestAllowlist:
    def test_unknown_fields_are_dropped(self):
        out = redact_session(
            {
                "external_id": "abc-123",
                "prompt": "deploy with " + AWS_KEY,
                "transcript_path": "/Users/gilad/.claude/projects/x.jsonl",
                "cwd": "/Users/gilad/code/api",
                "env": {"AWS_SECRET_ACCESS_KEY": AWS_SECRET},
            }
        )
        assert out == {"external_id": "abc-123"}

    def test_allowlist_is_exactly_these_fields(self):
        # Adding a field to the wire format must be a deliberate, reviewed change.
        assert set(SESSION_FIELDS) == {
            "external_id", "agent_vendor", "agent_version", "agent_model", "repo", "branch",
            "task_ref", "origin", "start_source", "end_reason",
        }

    def test_identifier_fields_drop_rather_than_scrub(self):
        out = redact_session({"agent_model": "claude opus; rm -rf /", "agent_version": GH_PAT})
        assert out == {}

    def test_session_id_must_be_an_id(self):
        assert redact_session({"external_id": "../../etc/passwd"}) == {}

    def test_enums(self):
        assert redact_session({"origin": "human", "start_source": "resume"}) == {"origin": "human", "start_source": "resume"}
        assert redact_session({"origin": "robot", "start_source": "x"}) == {}

    def test_branch_is_scrubbed_not_dropped(self):
        out = redact_session({"branch": "hotfix/" + STRIPE})
        assert out["branch"].startswith("hotfix/")
        assert STRIPE not in out["branch"]

    def test_values_are_length_limited(self):
        out = redact_session({"branch": "b" * 5000})
        assert len(out["branch"]) <= 200

    def test_non_string_values_dropped(self):
        assert redact_session({"repo": {"url": "x"}, "branch": ["main"], "agent_model": 5}) == {}


class TestReviewRegressions:
    """Bypasses found in review. Each must stay fixed."""

    @pytest.mark.parametrize(
        "text,secret",
        [
            ("fix/" + AWS_SECRET, AWS_SECRET),
            ("feat/Xq3_9fKd-Lm2PzR8vT1nB4yW-hJ6cE0aS5uG7iO_Nk", "Xq3_9fKd-Lm2PzR8vT1nB4yW-hJ6cE0aS5uG7iO_Nk"),
            ("fix/3f9a8c1d2e4b5a6978c0d1e2f3a4b5c6", "3f9a8c1d2e4b5a6978c0d1e2f3a4b5c6"),
            ("deploy_" + "a1b2c3d4" * 5, "a1b2c3d4" * 5),
            ("hotfix_" + STRIPE, STRIPE),
            ("x_" + GH_PAT, GH_PAT),
            ("xapp-1-A0123456789-" + "1234567890123-abcdefABCDEF0123456789", "abcdefABCDEF0123456789"),
            ("xoxe-1-" + "My4xLTEtNTE0MDgxNTgzMTk3", "My4xLTEtNTE0MDgxNTgzMTk3"),
        ],
    )
    def test_secret_shapes_are_redacted(self, text, secret):
        assert secret not in scrub(text)

    @pytest.mark.parametrize(
        "path",
        [
            "C:/Users/alice/work/secret-proj",
            "C:\\Users\\alice\\work\\secret-proj",
            "\\\\fileserver\\alice\\secret-proj",
            "~/work/secret-proj",
            "./secret-proj",
        ],
    )
    def test_local_paths_never_include_the_username(self, path):
        assert normalize_repo(path) == "secret-proj"

    def test_adversarial_prompt_is_fast(self):
        import time

        from flockit import taskref

        started = time.monotonic()
        taskref.from_prompt("please fix https://jira.acme.com/" + "a-" * 8000 + "/browse/ENG-1")
        taskref.from_prompt("http://" * 8000)
        scrub("x" * 5000 + "TOKEN" + "a-" * 5000)
        scrub(("TOKEN_" * 3000) + "=")
        assert time.monotonic() - started < 1.0

from collections.abc import AsyncGenerator
from collections.abc import Iterable
from datetime import datetime
from datetime import timedelta
from typing import Any
from unittest import mock
from urllib.parse import urlencode

import httpx
from httpx import codes

from pydantic import HttpUrl

import pytest
from pytest_httpx import HTTPXMock

from spotifagent.domain.entities.spotify import SpotifyScope
from spotifagent.domain.entities.spotify import SpotifyTokenState
from spotifagent.infrastructure.adapters.clients.spotify import SpotifyClientAdapter

from tests.unit.factories.spotify import SpotifyTokenStateFactory


class TestSpotifyClientAdapter:
    @pytest.fixture
    def mock_tenacity_sleep(self) -> Iterable[None]:
        retry_controller = SpotifyClientAdapter.make_user_api_call.retry  # type: ignore[attr-defined]
        original_sleep = retry_controller.sleep

        retry_controller.sleep = mock.AsyncMock(return_value=None)
        yield
        retry_controller.sleep = original_sleep

    @pytest.fixture
    async def spotify_client(self) -> AsyncGenerator[SpotifyClientAdapter]:
        spotify_client = SpotifyClientAdapter(
            client_id="dummy-client-id",
            client_secret="dummy-client-secret",
            redirect_uri=HttpUrl("https://example.com/callback"),
        )

        yield spotify_client

        await spotify_client.close()

    @pytest.fixture
    def token_state_expired(self, frozen_time: datetime, spotify_client: SpotifyClientAdapter) -> SpotifyTokenState:
        return SpotifyTokenStateFactory().build(
            expires_at=frozen_time - timedelta(seconds=spotify_client.token_buffer_seconds + 20),
        )

    def test__get_authorization_url(self, spotify_client: SpotifyClientAdapter) -> None:
        spotify_token_state = "dummy-token-state"

        url, state = spotify_client.get_authorization_url(
            scopes=[SpotifyScope.USER_READ_EMAIL, SpotifyScope.USER_READ_PRIVATE],
            state=spotify_token_state,
        )

        base_url = "https://accounts.spotify.com/authorize"
        query = (
            f"client_id=dummy-client-id"
            f"&response_type=code"
            f"&redirect_uri=https%3A%2F%2Fexample.com%2Fcallback"
            f"&scope=user-read-email+user-read-private"
            f"&state={state}"
        )
        assert url == HttpUrl(f"{base_url}?{query}")
        assert state == spotify_token_state

    async def test__exchange_code_for_token__nominal(
        self,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
        frozen_time: datetime,
    ) -> None:
        code = "test-code"
        form_data: dict[str, Any] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": str(spotify_client.redirect_uri),
        }
        response_json: dict[str, Any] = {
            "token_type": "bearer",
            "access_token": "dummy-access-token",
            "refresh_token": "dummy-refresh-token",
            "expires_in": 3600,
        }

        httpx_mock.add_response(
            url=str(spotify_client.token_endpoint),
            method="POST",
            match_headers={
                "Authorization": spotify_client._get_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            match_content=urlencode(form_data).encode("utf-8"),
            json=response_json,
        )

        token_state = await spotify_client.exchange_code_for_token(code)

        assert token_state.token_type == response_json["token_type"]
        assert token_state.access_token == response_json["access_token"]
        assert token_state.refresh_token == response_json["refresh_token"]
        assert token_state.expires_at == frozen_time + timedelta(seconds=response_json["expires_in"])

    async def test__exchange_code_for_token__exception_http_status(
        self,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
    ) -> None:
        httpx_mock.add_response(status_code=400, json={"detail": "Bad Request"})

        with pytest.raises(httpx.HTTPStatusError, match="Bad Request"):
            await spotify_client.exchange_code_for_token("test")

    @pytest.mark.parametrize("response_json_extra", [{}, {"refresh_token": "dummy-new-refresh_token"}])
    async def test__refresh_access_token__nominal(
        self,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
        frozen_time: datetime,
        response_json_extra: dict[str, Any],
    ) -> None:
        old_refresh_token = "dummy-old-refresh-token"

        form_data: dict[str, Any] = {
            "grant_type": "refresh_token",
            "refresh_token": old_refresh_token,
        }
        response_json: dict[str, Any] = {
            "token_type": "bearer",
            "access_token": "dummy-access-token",
            "expires_in": 3600,
            **response_json_extra,
        }

        httpx_mock.add_response(
            url=str(spotify_client.token_endpoint),
            method="POST",
            match_headers={
                "Authorization": spotify_client._get_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            match_content=urlencode(form_data).encode("utf-8"),
            json=response_json,
        )

        token_state = await spotify_client.refresh_access_token(old_refresh_token)

        assert token_state.token_type == response_json["token_type"]
        assert token_state.access_token == response_json["access_token"]
        assert token_state.refresh_token == response_json.get("refresh_token", old_refresh_token)
        assert token_state.expires_at == frozen_time + timedelta(seconds=response_json["expires_in"])

    async def test__refresh_access_token__exception_http_status(
        self,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
    ) -> None:
        httpx_mock.add_response(status_code=400, json={"detail": "Bad Request"})

        with pytest.raises(httpx.HTTPStatusError, match="Bad Request"):
            await spotify_client.refresh_access_token("dummy-refresh-token")

    @pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete", "head"])
    async def test__make_user_api_call__nominal(
        self,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
        token_state: SpotifyTokenState,
        method: str,
    ) -> None:
        response_json: dict[str, Any] = {"succeed": True}

        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method=method.upper(),
            match_headers={
                "Authorization": f"{token_state.token_type} {token_state.access_token}",
                "Content-Type": "application/json",
            },
            json=response_json,
        )

        response_data, response_token_state = await spotify_client.make_user_api_call(
            method=method,
            endpoint="/foo/bar",
            token_state=token_state,
        )
        assert response_data == response_json
        assert token_state == response_token_state

    async def test__make_user_api_call__no_content(
        self,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
        token_state: SpotifyTokenState,
    ) -> None:
        httpx_mock.add_response(status_code=codes.NO_CONTENT)

        response_data, _ = await spotify_client.make_user_api_call(
            method="GET",
            endpoint="/foo/bar",
            token_state=token_state,
        )
        assert response_data == {}

    async def test__make_user_api_call__access_token_expired(
        self,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
        frozen_time: datetime,
        token_state_expired: SpotifyTokenState,
    ) -> None:
        # First mock the refresh token endpoint.
        form_data: dict[str, Any] = {
            "grant_type": "refresh_token",
            "refresh_token": token_state_expired.refresh_token,
        }
        response_json: dict[str, Any] = {
            "token_type": "bearer",
            "access_token": "dummy-access-token",
            "refresh_token": "dummy-refresh-token",
            "expires_in": 3600,
        }
        httpx_mock.add_response(
            url=str(spotify_client.token_endpoint),
            method="POST",
            match_content=urlencode(form_data).encode("utf-8"),
            json=response_json,
        )

        # Then mock a dummy endpoint to make the call.
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            json={"succeed": True},
        )

        _, token_state = await spotify_client.make_user_api_call(
            method="GET",
            endpoint="/foo/bar",
            token_state=token_state_expired,
        )
        assert token_state.token_type == response_json["token_type"]
        assert token_state.access_token == response_json["access_token"]
        assert token_state.refresh_token == response_json["refresh_token"]
        assert token_state.expires_at == frozen_time + timedelta(seconds=response_json["expires_in"])

    async def test__make_user_api_call__access_token_enforced(
        self,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
        token_state: SpotifyTokenState,
        frozen_time: datetime,
    ) -> None:
        # First mock the refresh token endpoint.
        form_data: dict[str, Any] = {
            "grant_type": "refresh_token",
            "refresh_token": token_state.refresh_token,
        }
        response_json_token: dict[str, Any] = {
            "token_type": "bearer",
            "access_token": "dummy-access-token",
            "refresh_token": "dummy-refresh-token",
            "expires_in": 3600,
        }
        httpx_mock.add_response(
            url=str(spotify_client.token_endpoint),
            method="POST",
            match_content=urlencode(form_data).encode("utf-8"),
            json=response_json_token,
        )

        # Then mock a dummy 401 to enforce the refresh token.
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.UNAUTHORIZED,
        )
        # Then mock the final response because the refresh token is now valid.
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            json={"succeed": True},
        )

        response_data, token_state_updated = await spotify_client.make_user_api_call(
            method="GET",
            endpoint="/foo/bar",
            token_state=token_state,
        )
        assert response_data == {"succeed": True}

        assert token_state_updated.token_type == response_json_token["token_type"]
        assert token_state_updated.access_token == response_json_token["access_token"]
        assert token_state_updated.refresh_token == response_json_token["refresh_token"]
        assert token_state_updated.expires_at == frozen_time + timedelta(seconds=response_json_token["expires_in"])

    async def test__make_user_api_call__retry__not_on_404(
        self,
        spotify_client: SpotifyClientAdapter,
        token_state: SpotifyTokenState,
        httpx_mock: HTTPXMock,
    ) -> None:
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.NOT_FOUND,
        )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await spotify_client.make_user_api_call(
                method="GET",
                endpoint="/foo/bar",
                token_state=token_state,
            )
        assert exc_info.value.response.status_code == codes.NOT_FOUND
        assert len(httpx_mock.get_requests()) == 1

    async def test__make_user_api_call__retry__not_on_generic_error(
        self,
        spotify_client: SpotifyClientAdapter,
        token_state: SpotifyTokenState,
        httpx_mock: HTTPXMock,
    ) -> None:
        httpx_mock.add_exception(RuntimeError("Unexpected crash"))

        with pytest.raises(RuntimeError, match="Unexpected crash"):
            await spotify_client.make_user_api_call(
                method="GET",
                endpoint="/foo/bar",
                token_state=token_state,
            )
        assert len(httpx_mock.get_requests()) == 1

    async def test__make_user_api_call__retry__server_error(
        self,
        spotify_client: SpotifyClientAdapter,
        token_state: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        mock_tenacity_sleep: None,
    ) -> None:
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.INTERNAL_SERVER_ERROR,  # 500
        )
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.SERVICE_UNAVAILABLE,  # 503
        )
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.OK,  # 200
            json={"success": True},
        )

        response, _ = await spotify_client.make_user_api_call(
            method="GET",
            endpoint="/foo/bar",
            token_state=token_state,
        )
        assert response == {"success": True}
        assert len(httpx_mock.get_requests()) == 3

    async def test__make_user_api_call__retry__network_error(
        self,
        spotify_client: SpotifyClientAdapter,
        token_state: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        mock_tenacity_sleep: None,
    ) -> None:
        httpx_mock.add_exception(httpx.ConnectError("Network down"))
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.OK,
            json={"success": True},
        )

        response, _ = await spotify_client.make_user_api_call(
            method="GET",
            endpoint="/foo/bar",
            token_state=token_state,
        )
        assert response == {"success": True}
        assert len(httpx_mock.get_requests()) == 2

    async def test__make_user_api_call__retry__max_attempts_exceeded(
        self,
        spotify_client: SpotifyClientAdapter,
        token_state: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        mock_tenacity_sleep: None,
    ) -> None:
        for _ in range(5):
            httpx_mock.add_response(
                url=f"{spotify_client.BASE_URL}/foo/bar",
                method="GET",
                status_code=codes.INTERNAL_SERVER_ERROR,
            )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await spotify_client.make_user_api_call(
                method="GET",
                endpoint="/foo/bar",
                token_state=token_state,
            )

        assert exc_info.value.response.status_code == codes.INTERNAL_SERVER_ERROR
        assert len(httpx_mock.get_requests()) == 5

    async def test__make_user_api_call__retry__rate_limit__with_header(
        self,
        spotify_client: SpotifyClientAdapter,
        token_state: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        mock_tenacity_sleep: None,
    ) -> None:
        retry_after: int = 1
        expected_attempt: int = 2  # One 429 then one 200
        expected_wait: int = retry_after + 1  # Slept for 1 + 1 = 2 seconds

        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.TOO_MANY_REQUESTS,
            headers={"Retry-After": f"{retry_after}"},
        )
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.OK,
            json={"success": True},
        )

        # We patch asyncio.sleep to check that OUR code called it (no tenacity's sleep handled by fixture).
        with mock.patch("asyncio.sleep", new_callable=mock.AsyncMock) as mock_sleep:
            response, _ = await spotify_client.make_user_api_call(
                method="GET",
                endpoint="/foo/bar",
                token_state=token_state,
            )
        mock_sleep.assert_any_call(expected_wait)

        assert response == {"success": True}
        assert len(httpx_mock.get_requests()) == expected_attempt

    async def test__make_user_api_call__retry__rate_limit__without_header(
        self,
        spotify_client: SpotifyClientAdapter,
        token_state: SpotifyTokenState,
        httpx_mock: HTTPXMock,
        mock_tenacity_sleep: None,
    ) -> None:
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.TOO_MANY_REQUESTS,
        )
        httpx_mock.add_response(
            url=f"{spotify_client.BASE_URL}/foo/bar",
            method="GET",
            status_code=codes.OK,
            json={"success": True},
        )

        response, _ = await spotify_client.make_user_api_call(
            method="GET",
            endpoint="/foo/bar",
            token_state=token_state,
        )
        assert response == {"success": True}
        assert len(httpx_mock.get_requests()) == 2

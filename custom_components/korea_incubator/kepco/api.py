"""KEPCO API client for Home Assistant integration."""

from __future__ import annotations

import json
from typing import Dict, Any, Optional, Tuple

from bs4 import BeautifulSoup
from curl_cffi import AsyncSession

from .exceptions import KepcoAuthError, KepcoApiError
from ..const import LOGGER
from ..utils import RSAKey


class KepcoApiClient:
    """API client for KEPCO integration using curl_cffi."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the KEPCO API client."""
        self._session: AsyncSession = session
        self._username: Optional[str] = None
        self._password: Optional[str] = None

    def set_credentials(self, username: str, password: str) -> None:
        """Set authentication credentials."""
        self._username = username
        self._password = password

    async def async_get_session_and_rsa_key(self) -> Tuple[str, str, str]:
        """Get RSA key and session ID from KEPCO intro page."""
        url = "https://pp.kepco.co.kr:8030/intro.do"

        result = await self._session.get(url=url)
        result.raise_for_status()
        LOGGER.debug(f"Intro page response status: {result.status_code}")
        LOGGER.debug(f"Intro page response headers: {result.headers}")
        html_text = result.text

        soup = BeautifulSoup(html_text, "html.parser")

        rsa_modulus_tag = soup.find("input", {"id": "RSAModulus"})
        rsa_exponent_tag = soup.find("input", {"id": "RSAExponent"})
        sessid_tag = soup.find("input", {"id": "SESSID"})

        if not rsa_modulus_tag or not rsa_exponent_tag or not sessid_tag:
            raise KepcoAuthError(
                "Failed to get RSA modulus, exponent or SESSID from intro page HTML."
            )

        rsa_modulus = rsa_modulus_tag.get("value").strip()
        rsa_exponent = rsa_exponent_tag.get("value").strip()
        sessid = sessid_tag.get("value").strip()

        LOGGER.debug(f"Return KEPCO value {rsa_modulus}, {rsa_exponent}, {sessid}")

        return rsa_modulus, rsa_exponent, sessid

    async def async_login(self, username: str, password: str) -> bool:
        """Login to KEPCO with username and password."""
        self.set_credentials(username, password)
        try:
            (
                rsa_modulus,
                rsa_exponent,
                sessid,
            ) = await self.async_get_session_and_rsa_key()
        except KepcoAuthError as e:
            LOGGER.error(f"KEPCO Login failed: {e}")
            return False

        LOGGER.debug(f"KEPCO Login Request with {username} and {password}")

        try:
            rsa_key = RSAKey()
            rsa_key.set_public(rsa_modulus, rsa_exponent)

            encrypted_username_hex = rsa_key.encrypt(username)
            encrypted_password_hex = rsa_key.encrypt(password)

            if not encrypted_username_hex or not encrypted_password_hex:
                raise ValueError("RSA encryption failed")

        except Exception as e:
            LOGGER.error(f"RSA encryption failed: {e}")
            return False

        LOGGER.debug(
            f"KEPCO ID/PW: {encrypted_username_hex} / {encrypted_password_hex}, Session ID: {sessid}"
        )

        user_id = f"{sessid}_{encrypted_username_hex}"
        user_pw = f"{sessid}_{encrypted_password_hex}"

        login_url = "https://pp.kepco.co.kr:8030/login"

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://pp.kepco.co.kr:8030/intro.do",
            "Cookie": f"JSESSIONID={sessid}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        try:
            response = await self._session.post(
                login_url,
                data={"USER_ID": user_id, "USER_PW": user_pw},
                headers=headers,
                allow_redirects=True,
            )
            LOGGER.debug(f"Login response status: {response.status_code}")
            LOGGER.debug(f"Login response headers: {response.headers}")
            text = response.text
            LOGGER.debug(f"Login response body: {text}")
            
            if response.status_code == 200:
                # URL 체크 (None 안전하게 처리)
                url_str = str(response.url) if response.url else ""
                if "confirmInfo.do" in url_str or "main" in url_str:
                    return True
                
                # 응답 본문에서 로그인 성공 확인 (추가 검증)
                if "로그아웃" in text or "고객번호" in text or "전력사용량" in text:
                    LOGGER.info("Login success confirmed by response content")
                    return True
            
            LOGGER.error(
                f"KEPCO Login failed with status {response.status_code}: {text}"
            )
            return False
        except Exception as e:
            LOGGER.error(f"Login request failed: {e}")
            return False

    async def _request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated request to KEPCO API with auto re-login on auth errors."""
        try:
            response = await self._session.request(method, url, **kwargs)
            LOGGER.debug(
                f"API request to {url} response status: {response.status_code}"
            )
            LOGGER.debug(f"API request to {url} response headers: {response.headers}")
            LOGGER.debug(f"API request to {url} response body: {response.text}")
            
            # 인증 오류 확인 (401, 403)
            if response.status_code in (401, 403):
                LOGGER.warning(f"Authentication error (status {response.status_code}), attempting re-login.")
                raise KepcoAuthError(f"Authentication required: HTTP {response.status_code}")
            
            # JSON 파싱
            try:
                return json.loads(response.text)
            except json.JSONDecodeError as e:
                LOGGER.error(f"Invalid JSON response from {url}: {e}")
                raise KepcoApiError(f"Invalid JSON response: {e}")
                
        except KepcoAuthError:
            # 인증 오류에만 재로그인 시도
            if not self._username or not self._password:
                raise KepcoAuthError("Credentials not set for re-login")
            
            LOGGER.info("Attempting re-login after authentication error.")
            if await self.async_login(self._username, self._password):
                LOGGER.info("Re-login successful, retrying original request.")
                try:
                    response = await self._session.request(method, url, **kwargs)
                    LOGGER.debug(
                        f"Retry request to {url} response status: {response.status_code}"
                    )
                    
                    if response.status_code in (401, 403):
                        raise KepcoAuthError(f"Re-authentication failed: HTTP {response.status_code}")
                    
                    return json.loads(response.text)
                except json.JSONDecodeError as e:
                    raise KepcoApiError(f"Invalid JSON response after retry: {e}")
                except Exception as retry_e:
                    LOGGER.error(f"Retry request failed: {retry_e}")
                    raise KepcoApiError(f"Retry failed: {retry_e}") from retry_e
            else:
                LOGGER.error("KEPCO Re-login failed.")
                raise KepcoAuthError("Re-login failed")
                
        except Exception as e:
            # 기타 오류 (네트워크 등)는 재로그인 없이 바로 예외 발생
            LOGGER.error(f"API call to {url} failed: {e}")
            raise KepcoApiError(f"Request failed: {e}") from e

    async def async_get_recent_usage(self) -> Dict[str, Any]:
        """Get recent usage data from KEPCO."""
        url = "https://pp.kepco.co.kr:8030/low/main/recent_usage.do"
        return await self._request("POST", url, json={})

    async def async_get_usage_info(self) -> Dict[str, Any]:
        """Get usage information from KEPCO."""
        url = "https://pp.kepco.co.kr:8030/low/main/usage_info.do"
        return await self._request("POST", url, json={"tou": "N"})

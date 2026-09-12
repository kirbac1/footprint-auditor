"""Delivery of ownership-verification codes."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class CodeSender(Protocol):
    async def send(self, kind: str, destination: str, code: str) -> None: ...


def _mask(destination: str) -> str:
    if "@" in destination:
        local, _, domain = destination.partition("@")
        return f"{local[:1]}***@{domain}"
    return f"***{destination[-3:]}"


class ConsoleCodeSender:
    """Dev only: writes the code to the log. Settings refuses this in prod."""

    async def send(self, kind: str, destination: str, code: str) -> None:
        log.warning("DEV verification code for %s %s: %s", kind, _mask(destination), code)


class OutboxCodeSender:
    """Dev and test only: appends codes to a JSON-lines file so an end-to-end
    test can read them back. Settings refuses this in prod."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    async def send(self, kind: str, destination: str, code: str) -> None:
        line = json.dumps({"kind": kind, "destination": destination, "code": code})
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self._path.open("a") as f:
            f.write(line + "\n")


class AwsCodeSender:
    """SES for email, SNS for SMS."""

    def __init__(self, region: str, sender: str) -> None:
        import boto3  # only needed when this sender is configured

        self._ses = boto3.client("sesv2", region_name=region)
        self._sns = boto3.client("sns", region_name=region)
        self._sender = sender

    async def send(self, kind: str, destination: str, code: str) -> None:
        text = (
            f"Your exposure-auditor verification code is {code}. It expires in 10 minutes. "
            "If you did not ask for this, someone may be trying to scan with your details; ignore it."
        )
        if kind == "email":
            await asyncio.to_thread(
                self._ses.send_email,
                FromEmailAddress=self._sender,
                Destination={"ToAddresses": [destination]},
                Content={"Simple": {"Subject": {"Data": "Verification code"}, "Body": {"Text": {"Data": text}}}},
            )
        elif kind == "phone":
            await asyncio.to_thread(self._sns.publish, PhoneNumber=destination, Message=text)
        else:
            raise ValueError(f"cannot deliver a code to a {kind}")

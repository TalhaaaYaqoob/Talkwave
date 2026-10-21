# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-19

First open-source release of TalkWave.

### Added

- Visual workflow builder for voice agents, with AI-assisted workflow generation.
- Inbound and outbound telephony over Twilio, Vonage, and Vobiz, plus in-browser WebRTC calls and optional LiveKit transport.
- Outbound campaigns, LoopTalk AI test personas, knowledge base retrieval, and opt-in caller memory.
- Meeting agent for Zoom, Google Meet, and Teams through Recall.ai.
- Custom HTTP tools, web search, and Composio integrations.
- Every organization gets all features with no usage limits. Quota logic lives in one place (`services/subscription`) if you need to add your own.
- Docker Compose stack that builds the API and UI images locally.
- Contributor documentation, issue and pull request templates, and CI for linting, tests, Docker builds, and secret scanning.

[Unreleased]: https://github.com/TalhaaaYaqoob/talkwave/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/TalhaaaYaqoob/talkwave/releases/tag/v1.0.0

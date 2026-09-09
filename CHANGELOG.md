# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Made SQLite connection initialization race-safe so concurrent first requests share a single initialized connection.
- Return HTTP 400 for empty or non-string setlist names instead of a successful response or server error.

## [1.0.3] - 2026-09-08

### Changed

- Established the changelog at the plugin's current version.

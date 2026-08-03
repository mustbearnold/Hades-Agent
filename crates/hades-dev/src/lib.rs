//! Hades development harness: Rust tooling for the parity loop.
//!
//! Per ADR-0008, all Hades development tooling migrates from Python to Rust.
//! This crate hosts the shared harness primitives (terminal screen
//! emulation, PTY control) and, in later phases, the fixture validator,
//! control plane, replays, reference probes, and verify orchestration.

pub mod pty;
pub mod replay;
pub mod screen;

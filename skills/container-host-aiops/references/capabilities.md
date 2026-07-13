# container-host-aiops capabilities

> Preview / mock-only. **34 MCP tools** (26 read, 8 write) across the Docker
> Engine API (unix socket or TCP) and Portainer (management API + proxied Docker).
> Docker/Portainer API responses are mocked and need live verification.

Every tool is wrapped with the bundled `@governed_tool` harness (audit, policy,
token/runaway budget, undo, risk-tiers). All host-returned text is sanitized.

## Overview (read)

| Tool | Docker/Portainer path | Returns |
|------|-----------------------|---------|
| `overview` | `/info` + `/containers/json` + `/system/df` | host summary: platform, server version, container state rollup, disk headline |

## Containers (read)

| Tool | Path | Returns |
|------|------|---------|
| `list_containers` | `/containers/json?all=` | containers bucketed by state (running/exited/…), compact rows |
| `inspect_container` | `/containers/{id}/json` | full inspect (config, state, mounts, network) |
| `container_logs` | `/containers/{id}/logs?tail=N` | last N log lines (demuxed stdout+stderr) |
| `container_stats` | `/containers/{id}/stats?stream=false` | CPU% + memory% snapshot (Docker's own delta formula) |
| `container_top` | `/containers/{id}/top` | processes running inside the container |
| `container_restart_summary` | `/containers/json` + per-container inspect | restart count + exit code + OOM, worst-first |

## Images (read)

| Tool | Path | Returns |
|------|------|---------|
| `list_images` | `/images/json` | images (tags, size, dangling), largest first |
| `inspect_image` | `/images/{id}/json` + `/images/{id}/history` | inspect + build history (layers, sizes, commands) |
| `dangling_images` | `/images/json?filters=dangling` | untagged images + reclaimable bytes |
| `image_disk_usage` | `/system/df` (Images) | total, shared, reclaimable image bytes |

## Volumes (read)

| Tool | Path | Returns |
|------|------|---------|
| `list_volumes` | `/volumes` | named volumes (driver, mountpoint, scope) |
| `inspect_volume` | `/volumes/{name}` | one volume in detail |
| `dangling_volumes` | `/system/df` (Volumes, RefCount=0) | unreferenced volumes + reclaimable bytes |

## Networks (read)

| Tool | Path | Returns |
|------|------|---------|
| `list_networks` | `/networks` | networks bucketed by driver |
| `inspect_network` | `/networks/{id}` | driver, IPAM subnet/gateway, attached containers |

## System (read)

| Tool | Path | Returns |
|------|------|---------|
| `system_info` | `/info` | container/image counts, storage driver, kernel, resources |
| `system_version` | `/version` | version, API version, Go version, components |
| `system_df` | `/system/df` | disk-usage breakdown: images, containers, volumes, build cache |
| `system_events` | `/events?since=&until=` | recent daemon events, rolled up by type+action |

## Stacks — Portainer (read; requires a portainer target)

| Tool | Path | Returns |
|------|------|---------|
| `list_endpoints` | `/api/endpoints` | Portainer managed hosts (id, name, type, status, url) |
| `list_stacks` | `/api/stacks` | Portainer stacks (id, name, type, endpoint, status) |
| `stack_detail` | `/api/stacks/{id}` | one stack in detail (env, entrypoint, resource control) |

## Flagship analyses (read; injected or live)

| Tool | Inputs | Returns |
|------|--------|---------|
| `restart_loop_rca` | container restart rows (+ optional log tails) or live pull | crash-looping containers ranked by restart count, each with cause+action from exit code (137 OOM/SIGKILL, 143 SIGTERM, 139 segfault, 127 bad entrypoint, …) + a log tail |
| `resource_pressure_analysis` | CPU%/mem% samples or live pull | containers flagged near (≥80% of a threshold) / over, worst-first, with a recommendation |
| `image_and_volume_bloat` | dangling images + volumes + system/df, or live pull | prune candidates with reclaimable bytes, largest first |

## Writes (guarded)

| Tool | Risk | Path | Notes |
|------|:----:|------|-------|
| `restart_container` | med | `POST /containers/{id}/restart` | captures prior state for audit; no meaningful inverse |
| `stop_container` | med | `POST /containers/{id}/stop` | undo → `start_container` |
| `start_container` | med | `POST /containers/{id}/start` | undo → `stop_container` |
| `update_container` | med | `POST /containers/{id}/update` | captures prior CPU/memory limits; undo restores them |
| `remove_container` | **high** | `DELETE /containers/{id}` | `dry_run` + double-confirm; captures full inspect BEFORE; no undo |
| `prune_images` | **high** | `POST /images/prune` | `dry_run` LISTS candidates + reclaimable bytes first; no undo |
| `prune_volumes` | **high** | `POST /volumes/prune` | `dry_run` LISTS candidates + reclaimable bytes first; no undo |
| `recreate_stack` | **high** | `PUT /api/stacks/{id}/git/redeploy` | Portainer; captures prior stack; no undo |

## Not in scope

- Cluster orchestrators, hypervisors, storage appliances, backup products (separate AIops-tools)
- Creating containers/images/networks from scratch, `docker build`, registry push/pull, exec-into-container
- Swarm service scaling beyond a Portainer stack redeploy

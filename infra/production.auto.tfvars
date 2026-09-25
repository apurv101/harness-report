# Production is deployed by CI with no command-line variables. Keep the worker
# fleet enabled here so a normal deploy cannot silently remove all consumers.
enable_run_plane        = true
runner_dispatch_enabled = true
runner_warm_pool        = 2

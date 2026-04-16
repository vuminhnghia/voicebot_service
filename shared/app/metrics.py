from prometheus_client import Counter, Histogram

task_counter = Counter(
    "voicebot_task_total",
    "Total number of tasks by type and status",
    ["task_type", "status"],
)

task_duration = Histogram(
    "voicebot_task_duration_seconds",
    "Task end-to-end processing duration in seconds",
    ["task_type"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

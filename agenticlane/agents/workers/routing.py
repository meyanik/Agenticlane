"""Routing worker agent."""
from agenticlane.agents.workers.base import WorkerAgent


class RoutingWorker(WorkerAgent):
    """Worker for the ROUTE_GLOBAL and ROUTE_DETAILED stages."""

"""Tests verifying Workflow Studio Visual Graph and Table View Switcher.

Checks:
1. templates/index.html contains dual-view switcher controls and graph canvas elements
2. static/css/style.css contains responsive graph node, connector, and port styles
3. static/js/app.js exports setWorkflowView, renderWorkflowGraph, pan/zoom handlers
"""

import os
import unittest


class TestWorkflowStudioGraphView(unittest.TestCase):
    """Test suite for Workflow Studio graph and switcher frontend assets."""

    @classmethod
    def setUpClass(cls):
        cls.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.html_path = os.path.join(cls.base_dir, "templates", "index.html")
        cls.css_path = os.path.join(cls.base_dir, "static", "css", "style.css")
        cls.js_path = os.path.join(cls.base_dir, "static", "js", "app.js")

    def test_html_view_switcher_and_graph_canvas_elements(self):
        """index.html must include dual-view switcher buttons, table view, and graph canvas elements."""
        self.assertTrue(os.path.exists(self.html_path), "templates/index.html must exist")
        with open(self.html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # View switcher buttons
        self.assertIn('id="btnViewTable"', html)
        self.assertIn('id="btnViewGraph"', html)
        self.assertIn("setWorkflowView('table')", html)
        self.assertIn("setWorkflowView('graph')", html)

        # Both view containers
        self.assertIn('id="workflowTableView"', html)
        self.assertIn('id="workflowGraphView"', html)

        # Graph canvas layers
        self.assertIn('id="wfCanvasViewport"', html)
        self.assertIn('id="wfCanvasWorld"', html)
        self.assertIn('id="wfGraphSvgLayer"', html)
        self.assertIn('id="wfGraphNodesLayer"', html)
        self.assertIn('id="wfNodeDetailModal"', html)
        self.assertIn('id="wfGraphRuleSelect"', html)
        self.assertIn('id="wfGraphStepsPill"', html)

    def test_css_graph_node_and_connector_rules(self):
        """style.css must contain styling for graph nodes, colorful categories, and bezier connectors."""
        self.assertTrue(os.path.exists(self.css_path), "static/css/style.css must exist")
        with open(self.css_path, "r", encoding="utf-8") as f:
            css = f.read()

        # Switcher & Viewport
        self.assertIn(".view-switch-btn", css)
        self.assertIn(".wf-canvas-viewport", css)

        # Graph nodes & colorful types
        self.assertIn(".wf-graph-node", css)
        self.assertIn(".wf-graph-node.trigger", css)
        self.assertIn(".wf-graph-node.condition", css)
        self.assertIn(".wf-graph-node.urgency_detection", css)
        self.assertIn(".wf-graph-node.ai_analysis", css)
        self.assertIn(".wf-graph-node.action", css)
        self.assertIn(".wf-graph-node.approval", css)
        self.assertIn(".wf-graph-node.end", css)

        # Connectors & Ports
        self.assertIn(".wf-connector-path", css)
        self.assertIn(".wf-node-port", css)

    def test_js_graph_controller_functions(self):
        """app.js must define setWorkflowView, renderWorkflowGraph, pan/zoom, and modal handlers."""
        self.assertTrue(os.path.exists(self.js_path), "static/js/app.js must exist")
        with open(self.js_path, "r", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("function setWorkflowView", js)
        self.assertIn("function renderWorkflowGraph", js)
        self.assertIn("function initWorkflowGraphCanvas", js)
        self.assertIn("function wfGraphZoom", js)
        self.assertIn("function wfGraphFitView", js)
        self.assertIn("function openWfNodeModal", js)
        self.assertIn("function closeWfNodeModal", js)


if __name__ == "__main__":
    unittest.main()

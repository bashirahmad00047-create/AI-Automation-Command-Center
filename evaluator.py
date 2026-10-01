"""Condition Evaluator for Rule-Based Automation.

Evaluates complex conditions with dot-notation field access, type-coercion,
nested AND/OR logic, and produces comprehensive evaluation traces.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


class ConditionEvaluator:
    """Evaluates rules against incoming context with full execution tracing."""

    @staticmethod
    def get_field_value(data: Dict[str, Any], path: str) -> Any:
        """Retrieves a nested field value using dot-notation.
        Example: 'payload.metrics.cpu' or 'nlp.urgency'
        """
        if not path or not isinstance(data, dict):
            return None

        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, (list, tuple)) and part.isdigit():
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        return current

    @classmethod
    def evaluate_single(cls, condition: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Evaluates a single condition and returns (result, trace_info)."""
        field = condition.get("field", "")
        operator = condition.get("operator", "equals").lower()
        target_value = condition.get("value")

        actual_value = cls.get_field_value(context, field)

        passed = False
        notes = ""

        try:
            passed = cls._apply_operator(actual_value, operator, target_value)
        except Exception as e:
            passed = False
            notes = f"Evaluation error: {str(e)}"

        trace = {
            "field": field,
            "operator": operator,
            "target": target_value,
            "actual": actual_value,
            "passed": passed,
            "notes": notes
        }
        return passed, trace

    @classmethod
    def _apply_operator(cls, actual: Any, operator: str, target: Any) -> bool:
        # Standardize operators
        op_map = {
            "==": "equals",
            "=": "equals",
            "eq": "equals",
            "!=": "not_equals",
            "neq": "not_equals",
            ">": "greater_than",
            "gt": "greater_than",
            ">=": "greater_than_or_equal",
            "gte": "greater_than_or_equal",
            "<": "less_than",
            "lt": "less_than",
            "<=": "less_than_or_equal",
            "lte": "less_than_or_equal",
            "in": "in_list",
            "not_in": "not_in_list",
            "regex": "regex_match"
        }
        operator = op_map.get(operator, operator)

        if operator == "is_empty":
            return actual is None or actual == "" or (isinstance(actual, (list, dict, set)) and len(actual) == 0)

        if operator == "is_not_empty":
            return not (actual is None or actual == "" or (isinstance(actual, (list, dict, set)) and len(actual) == 0))

        if operator == "equals":
            if actual is None and target is None:
                return True
            if actual is None or target is None:
                return False
            # String comparison case-insensitive if strings
            if isinstance(actual, str) and isinstance(target, str):
                return actual.strip().lower() == target.strip().lower()
            return actual == target

        if operator == "not_equals":
            if isinstance(actual, str) and isinstance(target, str):
                return actual.strip().lower() != target.strip().lower()
            return actual != target

        # Numeric comparisons with automatic conversion
        if operator in ("greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"):
            if actual is None:
                return False
            try:
                num_actual = float(actual)
                num_target = float(target)
            except (ValueError, TypeError):
                return False

            if operator == "greater_than":
                return num_actual > num_target
            if operator == "greater_than_or_equal":
                return num_actual >= num_target
            if operator == "less_than":
                return num_actual < num_target
            if operator == "less_than_or_equal":
                return num_actual <= num_target

        if operator == "contains":
            if actual is None or target is None:
                return False
            if isinstance(actual, (list, tuple, set)):
                return target in actual
            return str(target).lower() in str(actual).lower()

        if operator == "not_contains":
            if actual is None or target is None:
                return True
            if isinstance(actual, (list, tuple, set)):
                return target not in actual
            return str(target).lower() not in str(actual).lower()

        if operator == "starts_with":
            if actual is None or target is None:
                return False
            return str(actual).lower().startswith(str(target).lower())

        if operator == "ends_with":
            if actual is None or target is None:
                return False
            return str(actual).lower().endswith(str(target).lower())

        if operator == "regex_match":
            if actual is None or target is None:
                return False
            return bool(re.search(str(target), str(actual), re.IGNORECASE))

        if operator == "in_list":
            if actual is None or target is None:
                return False
            if isinstance(target, (list, tuple, set)):
                return actual in target or str(actual) in [str(x) for x in target]
            if isinstance(target, str):
                items = [x.strip() for x in target.split(",")]
                return str(actual) in items
            return False

        if operator == "not_in_list":
            return not cls._apply_operator(actual, "in_list", target)

        return False

    @classmethod
    def evaluate_group(cls, condition_group: Dict[str, Any], context: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
        """Evaluates a group of conditions connected with AND/OR logic.
        Example group:
        {
            "logic": "AND",
            "conditions": [
                {"field": "payload.cpu", "operator": ">=", "value": 85},
                {"field": "nlp.urgency", "operator": ">=", "value": 70}
            ]
        }
        """
        if not condition_group:
            return True, [{"notes": "Empty condition group: evaluated as True"}]

        logic = condition_group.get("logic", "AND").upper()
        conditions = condition_group.get("conditions", [])

        if not conditions:
            return True, [{"notes": "No conditions defined in group: evaluated as True"}]

        trace_list = []
        results = []

        for item in conditions:
            # Handle nested group
            if "conditions" in item:
                sub_passed, sub_traces = cls.evaluate_group(item, context)
                results.append(sub_passed)
                trace_list.append({
                    "type": "nested_group",
                    "logic": item.get("logic", "AND"),
                    "passed": sub_passed,
                    "children": sub_traces
                })
            else:
                passed, trace = cls.evaluate_single(item, context)
                results.append(passed)
                trace_list.append(trace)

        if logic == "AND":
            overall_passed = all(results)
        elif logic == "OR":
            overall_passed = any(results)
        else:
            overall_passed = all(results)

        return overall_passed, trace_list

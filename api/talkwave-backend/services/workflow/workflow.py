import re
from collections import Counter
from typing import Dict, List

from api.services.workflow.dto import EdgeDataDTO, NodeDataDTO, NodeType, ReactFlowDTO
from api.services.workflow.errors import ItemKind, WorkflowError


class Edge:
    def __init__(self, source: str, target: str, data: EdgeDataDTO):
        self.source = source
        self.target = target

        self.label = data.label
        self.condition = data.condition

        self.data = data

    def get_function_name(self):
        # If label is empty, generate a default function name based on source and target
        if not self.label or not self.label.strip():
            return f"transition_to_{self.target}"
        return re.sub(r"[^a-z0-9]", "_", self.label.lower())

    def __eq__(self, other):
        if not isinstance(other, Edge):
            return False
        return self.source == other.source and self.target == other.target

    def __hash__(self):
        return hash((self.source, self.target))


class Node:
    def __init__(self, id: str, node_type: NodeType, data: NodeDataDTO):
        self.id, self.node_type, self.data = id, node_type, data
        self.out: Dict[str, "Node"] = {}  # forward nodes
        self.out_edges: List[Edge] = []  # forward edges with properties

        self.name = data.name
        self.prompt = data.prompt or ""
        self.is_static = False  # Static nodes are not supported - always override to False
        self.is_start = data.is_start
        self.is_end = data.is_end
        self.allow_interrupt = data.allow_interrupt
        self.extraction_enabled = data.extraction_enabled
        self.extraction_prompt = data.extraction_prompt
        self.extraction_variables = data.extraction_variables
        self.add_global_prompt = data.add_global_prompt
        self.detect_voicemail = data.detect_voicemail
        self.delayed_start = data.delayed_start
        self.delayed_start_duration = data.delayed_start_duration
        self.connection_greeting = data.connection_greeting
        self.web_search_enabled = data.web_search_enabled

        # Enhanced Agent Step fields
        self.tools = data.tools or []
        self.exit_conditions = data.exit_conditions or []
        self.knowledge_base = data.knowledge_base

        # Conversation constraints
        self.timer_duration = data.timer_duration
        self.max_rounds = data.max_rounds

        # If/Else node
        self.condition_text = data.condition_text

        # Categorize node
        self.categories = data.categories or []

        # Transfer node
        self.transfer_target = data.transfer_target
        self.is_literal = data.is_literal

        # Action Node fields
        self.description = data.description
        self.actions = data.actions or []
        self.execution_mode = data.execution_mode or "sequential"
        self.stop_on_error = data.stop_on_error or False

        self.data = data


class WorkflowGraph:
    """
    *All* business invariants (acyclic, cardinality, etc.) are verified here.
    The constructor accepts a validated ReactFlowDTO.
    """

    def __init__(self, dto: ReactFlowDTO):
        # build adjacency list
        self.nodes: Dict[str, Node] = {
            n.id: Node(n.id, n.type, n.data) for n in dto.nodes
        }

        # Store all edges
        self.edges: List[Edge] = []

        for e in dto.edges:
            source_node = self.nodes[e.source]
            target_node = self.nodes[e.target]

            # Create the edge with properties from dto
            edge = Edge(source=e.source, target=e.target, data=e.data)

            # Add to the edge list
            self.edges.append(edge)

            # Add to the source node's outgoing edges
            source_node.out_edges.append(edge)

            # Set up the node references for backward compatibility
            source_node.out[target_node.id] = target_node

        self._is_meeting_workflow = any(
            n.type == NodeType.meetingTrigger for n in dto.nodes
        )

        self._validate_graph()

        # For meeting workflows, the meetingTrigger is the entry point
        start_candidates = [n.id for n in dto.nodes if n.data.is_start]
        if not start_candidates and self._is_meeting_workflow:
            start_candidates = [
                n.id for n in dto.nodes if n.type == NodeType.meetingTrigger
            ]
        self.start_node_id = start_candidates[0]

        # Get a reference to the global node
        try:
            self.global_node_id = [
                n.id for n in dto.nodes if n.type == NodeType.globalNode
            ][0]
        except IndexError:
            self.global_node_id = None

    # -----------------------------------------------------------
    # validators
    # -----------------------------------------------------------
    def _validate_graph(self) -> None:
        errors: list[WorkflowError] = []

        # TODO: Figure out what kind of cyclic contraints can be applied, since there can be a cycle in the graph
        # try:
        #     self._assert_acyclic()
        # except ValueError as e:
        #     errors.append(
        #         WorkflowError(
        #             kind=ItemKind.workflow, id=None, field=None, message=str(e)
        #         )
        #     )

        errors.extend(self._assert_start_node())
        errors.extend(self._assert_end_node())
        errors.extend(self._assert_connection_counts())
        errors.extend(self._assert_global_node())
        errors.extend(self._assert_node_configs())
        if errors:
            raise ValueError(errors)

    def _assert_acyclic(self):
        color: Dict[str, str] = {}  # white / gray / black

        def dfs(n: Node):
            if color.get(n.id) == "gray":  # back-edge
                raise ValueError("workflow contains a cycle")
            if color.get(n.id) != "black":
                color[n.id] = "gray"
                for m in n.out.values():
                    dfs(m)
                color[n.id] = "black"

        for n in self.nodes.values():
            dfs(n)

    def _assert_start_node(self):
        errors: list[WorkflowError] = []
        start_node = [n for n in self.nodes.values() if n.data.is_start]

        if self._is_meeting_workflow:
            trigger_nodes = [
                n for n in self.nodes.values()
                if n.node_type == NodeType.meetingTrigger
            ]
            if not trigger_nodes and not start_node:
                errors.append(
                    WorkflowError(
                        kind=ItemKind.workflow,
                        id=None,
                        field=None,
                        message="Meeting workflow must have a meetingTrigger node",
                    )
                )
            return errors

        if not start_node:
            errors.append(
                WorkflowError(
                    kind=ItemKind.workflow,
                    id=None,
                    field=None,
                    message="Workflow must have exactly one start node",
                )
            )
        elif len(start_node) > 1:
            errors.append(
                WorkflowError(
                    kind=ItemKind.workflow,
                    id=None,
                    field=None,
                    message="Workflow must have exactly one start node",
                )
            )
        return errors

    def _assert_global_node(self):
        errors: list[WorkflowError] = []
        global_node = [
            n for n in self.nodes.values() if n.node_type == NodeType.globalNode
        ]
        if not len(global_node) <= 1:
            errors.append(
                WorkflowError(
                    kind=ItemKind.workflow,
                    id=None,
                    field=None,
                    message="Workflow must have at most one global node",
                )
            )
        return errors

    def _assert_end_node(self):
        errors: list[WorkflowError] = []

        if self._is_meeting_workflow:
            summary_nodes = [
                n for n in self.nodes.values()
                if n.node_type == NodeType.meetingSummary
            ]
            end_node = [n for n in self.nodes.values() if n.data.is_end]
            if not summary_nodes and not end_node:
                errors.append(
                    WorkflowError(
                        kind=ItemKind.workflow,
                        id=None,
                        field=None,
                        message="Meeting workflow must have a meetingSummary node",
                    )
                )
            return errors

        end_node = [n for n in self.nodes.values() if n.data.is_end]
        if not end_node:
            errors.append(
                WorkflowError(
                    kind=ItemKind.workflow,
                    id=None,
                    field=None,
                    message="Workflow must have exactly one end node",
                )
            )

        elif len(end_node) > 1:
            errors.append(
                WorkflowError(
                    kind=ItemKind.workflow,
                    id=None,
                    field=None,
                    message="Workflow must have exactly one end node",
                )
            )
        return errors

    def _assert_connection_counts(self):
        errors: list[WorkflowError] = []

        out_deg = Counter()
        in_deg = Counter()
        for n in self.nodes.values():  # init counters
            out_deg[n.id] = in_deg[n.id] = 0
        for src, n in self.nodes.items():  # compute degrees
            for m in n.out.values():
                out_deg[src] += 1
                in_deg[m.id] += 1

        for n in self.nodes.values():
            in_d, out_d = in_deg[n.id], out_deg[n.id]

            match n.node_type:
                case NodeType.startNode:
                    if in_d != 0 or out_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message=f"StartNode must have at least 1 outgoing edge",
                            )
                        )
                case NodeType.endNode:
                    # End nodes can optionally hand off to ONE action node
                    # before final call termination.
                    if in_d < 1 or out_d > 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message="EndNode must have at least 1 incoming edge and at most 1 outgoing edge",
                            )
                        )
                case NodeType.agentNode:
                    if in_d < 1 or out_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message=f"Worker must have at least 1 incoming and 1 outgoing edge",
                            )
                        )
                case NodeType.actionNode:
                    if in_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message=f"Action node must have at least 1 incoming edge",
                            )
                        )
                case NodeType.callVariables:
                    # Post-call data hub: fed by the End node, optionally fans
                    # out to action node(s).
                    if in_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message="Call Variables node must have at least 1 incoming edge",
                            )
                        )
                case NodeType.ifElse:
                    if in_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message="If/Else node must have at least 1 incoming edge",
                            )
                        )
                case NodeType.categorize:
                    if in_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message="Categorize node must have at least 1 incoming edge",
                            )
                        )
                case NodeType.transfer:
                    if in_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message="Transfer node must have at least 1 incoming edge",
                            )
                        )
                case NodeType.meetingTrigger:
                    if in_d != 0 or out_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message="Meeting Trigger must have no incoming edges and at least 1 outgoing edge",
                            )
                        )
                case NodeType.meetingSummary:
                    if in_d < 1:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.node,
                                id=n.id,
                                field=None,
                                message="Meeting Summary must have at least 1 incoming edge",
                            )
                        )

        return errors

    def _assert_node_configs(self):
        """Validate node-specific configuration constraints."""
        errors: list[WorkflowError] = []

        for node in self.nodes.values():
            # Validate StartNode constraints
            if node.node_type == NodeType.startNode:
                # Start nodes require a prompt
                if not node.prompt or len(node.prompt.strip()) == 0:
                    errors.append(
                        WorkflowError(
                            kind=ItemKind.node,
                            id=node.id,
                            field="prompt",
                            message="Start node requires a prompt",
                        )
                    )

            # Validate AgentNode constraints
            elif node.node_type == NodeType.agentNode:
                # Agent nodes require a prompt
                if not node.prompt or len(node.prompt.strip()) == 0:
                    errors.append(
                        WorkflowError(
                            kind=ItemKind.node,
                            id=node.id,
                            field="prompt",
                            message="Agent node requires a prompt",
                        )
                    )

            # Validate ActionNode constraints
            elif node.node_type == NodeType.actionNode:
                # Action nodes don't require a prompt, but should have at least one action
                # This is optional - you may want actions to be configured
                pass

            # Validate GlobalNode constraints
            elif node.node_type == NodeType.globalNode:
                # Global nodes require a prompt
                if not node.prompt or len(node.prompt.strip()) == 0:
                    errors.append(
                        WorkflowError(
                            kind=ItemKind.node,
                            id=node.id,
                            field="prompt",
                            message="Global node requires a prompt",
                        )
                    )

            # Validate EndNode constraints
            elif node.node_type == NodeType.endNode:
                # End nodes require a prompt
                if not node.prompt or len(node.prompt.strip()) == 0:
                    errors.append(
                        WorkflowError(
                            kind=ItemKind.node,
                            id=node.id,
                            field="prompt",
                            message="End node requires a prompt",
                        )
                    )

                # Optional post-end flow: EndNode may point to exactly one
                # ActionNode (legacy) or one Call Variables hub node (which then
                # fans out to action nodes).
                for edge in node.out_edges:
                    target_node = self.nodes.get(edge.target)
                    if not target_node or target_node.node_type not in (
                        NodeType.actionNode,
                        NodeType.callVariables,
                    ):
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.edge,
                                id=f"{edge.source}->{edge.target}",
                                field=None,
                                message="End node outgoing edge must target an Action node or Call Variables node",
                            )
                        )

            # Validate Call Variables (post-call hub) constraints
            elif node.node_type == NodeType.callVariables:
                # If it routes anywhere, every outgoing edge must hit an Action
                # node (the hub itself runs nothing; it just organizes data).
                for edge in node.out_edges:
                    target_node = self.nodes.get(edge.target)
                    if not target_node or target_node.node_type != NodeType.actionNode:
                        errors.append(
                            WorkflowError(
                                kind=ItemKind.edge,
                                id=f"{edge.source}->{edge.target}",
                                field=None,
                                message="Call Variables node outgoing edge must target an Action node",
                            )
                        )

            # Validate If/Else constraints
            elif node.node_type == NodeType.ifElse:
                if not node.condition_text or len(node.condition_text.strip()) == 0:
                    errors.append(
                        WorkflowError(
                            kind=ItemKind.node,
                            id=node.id,
                            field="condition_text",
                            message="If/Else node requires a condition",
                        )
                    )

            # Validate Categorize constraints
            elif node.node_type == NodeType.categorize:
                if not node.categories or len(node.categories) < 2:
                    errors.append(
                        WorkflowError(
                            kind=ItemKind.node,
                            id=node.id,
                            field="categories",
                            message="Categorize node requires at least 2 categories",
                        )
                    )

            # Validate Transfer constraints
            elif node.node_type == NodeType.transfer:
                if not node.prompt or len(node.prompt.strip()) == 0:
                    errors.append(
                        WorkflowError(
                            kind=ItemKind.node,
                            id=node.id,
                            field="prompt",
                            message="Transfer node requires a message",
                        )
                    )
                # A transfer node without a destination is dead weight — the
                # telephony layer has nothing to dial. The destination can be
                # a literal phone/SIP URI ("+15551234567", "sip:agent@host")
                # or a template variable filled in at runtime
                # ("{callback_number}", "{billing_phone}"). Either is fine;
                # an empty / whitespace-only string is not.
                if not node.transfer_target or len(node.transfer_target.strip()) == 0:
                    errors.append(
                        WorkflowError(
                            kind=ItemKind.node,
                            id=node.id,
                            field="transfer_target",
                            message=(
                                "Transfer node requires a destination — enter a "
                                "phone number (e.g. +15551234567), a SIP URI, or "
                                "a template variable like {callback_number} that "
                                "an upstream agent fills in"
                            ),
                        )
                    )

        return errors

# Project Management Workflow

**Location**: `kg-automation/workflows/project-mgmt.md`  
**Purpose**: Instructions for AI systems on Kent's project management system  
**Last Updated**: 2025-09-24

## Overview

Kent uses a two-tier project management system:
- **Strategic**: `project-roadmap.md` - High-level objectives, milestones, dependencies
- **Tactical**: `kg-tasks.md` - Immediate actionable tasks with detailed instructions

## AI System Responsibilities

### 1. Session Initialization
**MANDATORY** - Read these files in order:
1. `project-roadmap.md` - For strategic context and current focus
2. `kg-tasks.md` - For immediate task status and priorities

### 2. Task Creation Protocol
**When to create tasks**: If conversation results in 5+ manual steps for Kent

**Process**:
1. Identify if task is strategic (roadmap update) or tactical (immediate action)
2. Use templates from `kg-tasks.md`
3. Include specific step-by-step instructions
4. Estimate time required
5. Note conversation source and date

### 3. Task Management Rules

#### Creating New Tasks
```markdown
### Task: [Descriptive Name]
**Status**: 🟢 **Priority**: [High/Medium/Low]  
**Source**: [AI System] conversation - [Date] - [Brief context]  
**Estimated Time**: [Time estimate]  
**Related Roadmap Objective**: [Link to specific objective from project-roadmap.md]

**Context**: [Why this task exists, what it accomplishes]

**Steps to Complete**:
1. [ ] Specific step 1 with details
2. [ ] Specific step 2 with details
3. [ ] Etc.

**Notes**: [Any gotchas, prerequisites, or clarifications]
```

#### Status Indicators
- 🟢 **Ready**: Kent can start immediately, no blockers
- 🟡 **In Progress**: Kent is actively working on this
- 🔴 **Blocked**: Waiting on external dependencies
- ✅ **Complete**: Task finished (move to kg-tasks-completed.md)
- ❌ **Cancelled**: No longer needed

#### Blocker Handling Protocol
If Kent encounters a blocker during task execution:
1. **Mark task 🔴 Blocked** immediately
2. **Capture exact sub-step** where blocker occurred in task notes
3. **Create temporary troubleshooting task** linked to parent task
4. **Document blocker details** for resolution or escalation

#### Priority Guidelines
- **High**: Blocks other work or is time-sensitive
- **Medium**: Important but not blocking
- **Low**: Nice to have when time allows

### 4. Conversation Outcomes

#### Task Generation Triggers
- Setup/configuration with multiple steps
- Learning new tools or processes
- Multi-step integrations
- Development tasks requiring research

#### Documentation Updates
- Update `project-roadmap.md` when objectives change
- Update `kg-tasks.md` when adding/modifying tasks
- Move completed tasks to `kg-tasks-completed.md`

### 5. Cross-AI System Coordination

#### Handoff Protocol
When recommending Kent switch AI systems:
1. Update current task status in `kg-tasks.md`
2. Note handoff reason in task notes
3. Include specific context for receiving AI system

#### Context Sharing
- Always reference strategic context from `project-roadmap.md`
- Include relevant completed tasks for historical context
- Note capability limitations that led to handoffs

### 6. File Management

#### File Locations
- **Strategic**: `project-roadmap.md` (repo root)
- **Tactical**: `kg-tasks.md` (repo root)  
- **Completed**: `kg-tasks-completed.md` (repo root)
- **This Workflow**: `kg-automation/workflows/project-mgmt.md`

#### Update Responsibilities
- **Any AI**: Can add tasks, update status
- **Weekly Review**: Kent reviews and reorganizes
- **Strategic Updates**: Require Kent's input/approval

## Template Usage

### For Development Tasks
Use the "Multi-Step Development Task Template" from `kg-tasks.md` which includes:
- Prerequisites
- Research steps
- Implementation details
- Testing procedures
- Documentation requirements

### For General Tasks
Use the "Standard Task Template" with clear step-by-step instructions

## Quality Standards

### Task Descriptions Must Include:
- **Context**: Why the task matters
- **Specific Steps**: No ambiguous instructions
- **Success Criteria**: How Kent knows it's complete
- **Time Estimates**: Realistic expectations
- **Prerequisites**: What must be done first

### Avoid:
- Vague instructions ("set up X")
- Missing context ("do Y")
- Steps that assume expert knowledge
- Tasks without clear completion criteria

## AI System Integration

### Claude
- Strong at strategic planning and detailed step breakdown
- Good for complex multi-step technical tasks
- Can update files directly via artifacts

### ChatGPT  
- Good for research and learning tasks
- Strong at providing alternative approaches
- Useful for validation and review

### Gemini
- Good for cross-platform considerations
- Strong at integration planning
- Useful for risk assessment

### GitHub Copilot
- Code-focused tasks only
- Implementation assistance
- Code review and optimization

## Success Metrics

### Task Management Effectiveness
- Tasks completed vs. created
- Average time from creation to completion
- Number of tasks requiring clarification

### Strategic Alignment
- Progress toward roadmap objectives
- Milestone completion rate
- Successful AI system handoffs

---

## Change Log
- **2025-09-24**: Initial workflow documentation created
- **2025-09-24**: Added blocker handling protocol, roadmap linking requirement, status dashboard

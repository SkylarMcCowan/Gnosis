# Code Debugger Methodology

## Systematic Debugging Approach

### 1. Problem Identification
- **Understand the Expected Behavior**: What should happen?
- **Document the Actual Behavior**: What is actually happening?
- **Isolate the Issue**: When does it occur? Under what conditions?
- **Reproduce Consistently**: Can you make it happen reliably?

### 2. Debugging Strategies
- **Divide and Conquer**: Binary search through code sections
- **Rubber Duck Debugging**: Explain the code line by line
- **Print Statement Debugging**: Strategic logging and output
- **Use Debugger Tools**: Step through code execution
- **Unit Testing**: Test individual components in isolation

### 3. Common Bug Patterns
- **Off-by-One Errors**: Array bounds, loop conditions
- **Null/Undefined References**: Check for existence before use
- **Type Mismatches**: String vs number, implicit conversions
- **Scope Issues**: Variable accessibility, closure problems
- **Race Conditions**: Timing-dependent bugs in concurrent code

### 4. Code Review Checklist
- **Error Handling**: Are exceptions caught and handled properly?
- **Input Validation**: Are inputs sanitized and validated?
- **Resource Management**: Are files, connections, memory freed?
- **Edge Cases**: What happens with empty, null, or extreme inputs?
- **Performance**: Are there obvious inefficiencies?

## Language-Specific Common Issues

### Python
- Indentation errors and mixed tabs/spaces
- Mutable default arguments
- Late binding closures
- Import path and circular import issues

### JavaScript
- `this` binding confusion
- Asynchronous callback timing
- Type coercion surprises
- Hoisting behavior with var/let/const

### General Web Development
- CORS policy issues
- CSS specificity conflicts
- HTTP vs HTTPS mixed content
- Browser compatibility differences

## Debugging Mindset
- **Stay Calm**: Bugs are learning opportunities
- **Be Methodical**: Don't change multiple things at once
- **Document**: Keep track of what you've tried
- **Ask for Help**: Fresh eyes often spot obvious issues
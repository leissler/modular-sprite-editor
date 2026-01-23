from typing import Any, List, Optional
import copy

class UndoManager:
    """Generic Snapshot-based Undo Manager."""
    
    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self._stack: List[Any] = []
        self._pointer: int = -1
        self._is_undoing: bool = False

    def push_state(self, state: Any) -> None:
        """Push a NEW state to the history. Removes any redo history."""
        if self._is_undoing:
            return

        # If we are not at the end, truncate forward history (Redo)
        if self._pointer < len(self._stack) - 1:
             self._stack = self._stack[:self._pointer + 1]
             
        # Check for duplicate state (ignore if identical to current HEAD)
        if self._pointer >= 0:
            if self._stack[self._pointer] == state:
                return

        # Add new state
        # We assume 'state' is already a Snapshot (clone) provided by the caller
        self._stack.append(state)
        self._pointer += 1
        
        # Limit history
        if len(self._stack) > self.max_history:
            self._stack.pop(0)
            self._pointer -= 1

    def undo(self) -> Optional[Any]:
        """Move back in history and return the previous state."""
        if self._pointer > 0:
            self._pointer -= 1
            self._is_undoing = True
            try:
                state = self._stack[self._pointer]
                # Return a COPY of the state, so the stored snapshot remains immutable
                # We use the same 'clone' mechanism if it's an object with .clone(), or deepcopy?
                # Actually, the model .clone() uses to_dict/from_dict, which is deep enough.
                # But here we are returning generic Any. 
                # Ideally the Consumer should clone it before applying if they plan to modify it further?
                # No, the Consumer will *Replace* their current state with this state.
                # So if they modify the *active* object later, it shouldn't affect the snapshot in stack.
                # So we must return a Clone.
                if hasattr(state, "clone"):
                    return state.clone()
                else:
                    return copy.deepcopy(state)
            finally:
                self._is_undoing = False
        return None

    def redo(self) -> Optional[Any]:
        """Move forward in history and return the next state."""
        if self._pointer < len(self._stack) - 1:
            self._pointer += 1
            self._is_undoing = True
            try:
                 state = self._stack[self._pointer]
                 if hasattr(state, "clone"):
                    return state.clone()
                 else:
                    return copy.deepcopy(state)
            finally:
                self._is_undoing = False
        return None

    def can_undo(self) -> bool:
        return self._pointer > 0

    def can_redo(self) -> bool:
        return self._pointer < len(self._stack) - 1
        
    def reset(self):
        self._stack = []
        self._pointer = -1

"""The four public modes; metadata travels with local and remote inputs."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    number: int
    initial: bool
    correct: bool
    space: bool


def mode(number):
    if type(number) is not int or number not in (1, 2, 3, 4):
        raise ValueError('mode must be an integer from 1 to 4')
    return Mode(number, number == 1, number >= 3, number == 4)


def requested(meta):
    # Older saved inputs retain their original default execution behavior.
    value = meta.get('execution', {}).get('mode')
    return None if value is None else mode(value)

"""Norwegian Organisation Number validation and normalization."""

from __future__ import annotations

import re

# Norwegian standard weights for Modulus 11 calculation (left to right for digits 1-8)
MOD11_WEIGHTS = [3, 2, 7, 6, 5, 4, 3, 2]


def normalize_org_number(val: str | int | None) -> str:
    """Extract clean 9 digits from any formatted string (e.g. 'NO 923 609 016 MVA')."""
    if val is None:
        return ""
    digits = re.sub(r"\D", "", str(val))
    return digits


def is_valid_mod11(digits: str) -> bool:
    """Verify that a 9-digit string satisfies the Norwegian Modulus 11 control digit algorithm."""
    if len(digits) != 9 or not digits.isdigit():
        return False
    
    first_eight = [int(c) for c in digits[:8]]
    control_digit = int(digits[8])
    
    weighted_sum = sum(d * w for d, w in zip(first_eight, MOD11_WEIGHTS))
    remainder = weighted_sum % 11
    
    if remainder == 0:
        expected_control = 0
    elif remainder == 1:
        # Remainder 1 cannot yield a single-digit control number; invalid organisation number
        return False
    else:
        expected_control = 11 - remainder
        
    return control_digit == expected_control


def validate_org_number(val: str | int | None) -> str:
    """
    Validate and return the clean 9-digit organisation number.
    Raises ValueError if invalid format or failed Modulus 11 checksum.
    """
    cleaned = normalize_org_number(val)
    if len(cleaned) != 9:
        raise ValueError(f"Organisation number must contain exactly 9 digits, got {len(cleaned)} from {val!r}")
    if not is_valid_mod11(cleaned):
        raise ValueError(f"Organisation number {cleaned} failed Norwegian Modulus 11 checksum verification")
    return cleaned

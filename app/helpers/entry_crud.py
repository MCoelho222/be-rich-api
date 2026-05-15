from typing import Any, Protocol, TypeVar
from uuid import UUID
from fastapi import HTTPException
from sqlmodel import Session, select

from app.helpers.installments import handle_installments_split, add_months


ModelT = TypeVar("ModelT")


class SupportsModelDump(Protocol):
    def model_dump(self, *, exclude_unset: bool = False) -> dict[str, Any]:
        ...


def get_entry_or_404(session: Session, model: type[ModelT], entry_id: UUID, detail: str) -> ModelT:
    entry = session.get(model, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=detail)
    return entry


def find_entry_in_both_tables(
    session: Session,
    model_fixed: type[ModelT],
    model_unfixed: type[ModelT],
    entry_id: UUID,
    is_fixed: bool,
    detail: str
) -> tuple[ModelT, bool]:
    """
    Find an entry in either the fixed or unfixed table.
    Returns a tuple of (entry, needs_migration).
    
    needs_migration is True if the entry is in the wrong table and needs to be moved.
    """
    target_model = model_fixed if is_fixed else model_unfixed
    other_model = model_unfixed if is_fixed else model_fixed
    
    # Try to find in the target table first
    entry = session.get(target_model, entry_id)
    if entry:
        return entry, False  # Found in correct table, no migration needed
    
    # Try to find in the other table
    entry = session.get(other_model, entry_id)
    if entry:
        return entry, True  # Found in wrong table, migration needed
    
    # Not found in either table
    raise HTTPException(status_code=404, detail=detail)


def find_related_installments(session: Session, model: type[ModelT], entry: ModelT) -> list[ModelT]:
    """
    Find all entries that are part of the same installment series.
    Matches based on all fields except id, created_at, updated_at, and installment.
    """
    if not entry.installment or "/" not in entry.installment:
        return []
    
    # Build the query to find related installments
    query = select(model)
    
    # Match on all relevant fields (excluding id, created_at, updated_at, installment)
    entry_dict = entry.model_dump()
    
    for key, value in entry_dict.items():
        if key not in ['id', 'created_at', 'updated_at', 'installment']:
            query = query.where(getattr(model, key) == value)
    
    # Also filter for entries with installment field (same series pattern)
    # We'll match entries with the same installment total (e.g., "x/5" where 5 is the total)
    installment_parts = entry.installment.split("/")
    if len(installment_parts) == 2:
        total_installments = installment_parts[1]
        query = query.where(model.installment.like(f"%/{total_installments}"))
    
    results = session.exec(query).all()
    return list(results)


def _recalculate_installment_dates(
    related_entries: list[ModelT],
    current_entry_installment_number: int,
    new_created_at,
) -> None:
    """Recalculate dates for all installments based on a new date for one installment."""
    # Calculate what the first installment's date should be
    first_installment_date = add_months(new_created_at, -(current_entry_installment_number - 1))
    
    # Update dates for all related installments
    for related_entry in related_entries:
        entry_installment_num = int(related_entry.installment.split("/")[0])
        related_entry.created_at = add_months(first_installment_date, entry_installment_num - 1)


def _update_related_installments_same_count(
    session: Session,
    related_entries: list[ModelT],
    entry_data: dict[str, Any],
    db_entry: ModelT,
    entry_id: UUID,
) -> ModelT:
    """Update all installments in a series when NOT changing the installment count."""
    updated_entries = []
    
    if 'created_at' in entry_data:
        # Parse which installment this is (e.g., "3/5" -> installment 3)
        installment_number = int(db_entry.installment.split("/")[0])
        new_created_at = entry_data['created_at']
        
        # Recalculate all dates
        _recalculate_installment_dates(related_entries, installment_number, new_created_at)
        
        # Apply other updates (except created_at which we already set)
        for related_entry in related_entries:
            for key, value in entry_data.items():
                if key != 'created_at':
                    setattr(related_entry, key, value)
            session.add(related_entry)
            updated_entries.append(related_entry)
    else:
        # No created_at change - just update all related installments with same values
        for related_entry in related_entries:
            for key, value in entry_data.items():
                setattr(related_entry, key, value)
            session.add(related_entry)
            updated_entries.append(related_entry)
    
    session.commit()
    
    # Refresh and return the original entry we were asked to update
    for entry in updated_entries:
        session.refresh(entry)
    original_entry = next((e for e in updated_entries if e.id == entry_id), updated_entries[0])
    return original_entry


def _handle_installment_count_change(
    session: Session,
    model: type[ModelT],
    db_entry: ModelT,
    entry_data: dict[str, Any],
    related_entries: list[ModelT],
    new_installment_count: int,
    current_installment_count: int,
) -> ModelT:
    """Handle changing the installment count - delete old series and create new one."""
    # Find the first installment to preserve its created_at
    first_entry = next((e for e in related_entries if e.installment.startswith("1/")), related_entries[0])
    original_created_at = first_entry.created_at
    
    # Calculate the ORIGINAL total amount BEFORE applying any updates
    original_total_amount = db_entry.amount * current_installment_count
    
    # Check if amount is actually being changed (not just sent with same value)
    amount_is_changing = 'amount' in entry_data and entry_data['amount'] != db_entry.amount
    
    # Apply updates to db_entry
    for key, value in entry_data.items():
        setattr(db_entry, key, value)
    
    # Calculate the total amount for the new installment series
    if not amount_is_changing:
        # No amount change - redistribute original total
        total_amount = original_total_amount
    else:
        # Amount was changed - each installment gets this new amount
        total_amount = entry_data['amount'] * new_installment_count
    
    # Delete all old installments
    for old_entry in related_entries:
        session.delete(old_entry)
    
    # Create a new base entry with the updated data and total amount
    db_entry.amount = total_amount
    db_entry.created_at = original_created_at
    db_entry.installment = None  # Reset installment field before splitting
    
    # Create new installments
    db_entries = handle_installments_split(db_entry, new_installment_count)
    
    session.add_all(db_entries)
    session.commit()
    for entry in db_entries:
        session.refresh(entry)
    
    return db_entries[0]


def _create_installment_series_from_single(
    session: Session,
    db_entry: ModelT,
    entry_data: dict[str, Any],
    installment_count: int,
) -> ModelT:
    """Convert a single entry into an installment series."""
    for key, value in entry_data.items():
        setattr(db_entry, key, value)
    
    db_entries = handle_installments_split(db_entry, installment_count)
    
    session.add_all(db_entries)
    session.commit()
    for entry in db_entries:
        session.refresh(entry)
    
    return db_entries[0]


def update_entry(
    session: Session,
    model: type[ModelT],
    entry_id: UUID,
    entry: SupportsModelDump,
    installments: int | None,
    detail: str,
    ) -> ModelT:
    """Update an entry, handling installment series logic when applicable."""
    db_entry = get_entry_or_404(session, model, entry_id, detail) 
    entry_data = entry.model_dump(exclude_unset=True)
    # Check if the entry is part of an installment series
    if db_entry.installment and "/" in db_entry.installment:
        related_entries = find_related_installments(session, model, db_entry)
        
        if related_entries:
            current_installment_count = int(db_entry.installment.split("/")[1])
            
            # Check if we're changing the installment count
            if installments and installments > 1 and installments != current_installment_count:
                return _handle_installment_count_change(
                    session, model, db_entry, entry_data, related_entries,
                    installments, current_installment_count
                )
            else:
                # NOT changing installment count - update all related installments
                return _update_related_installments_same_count(
                    session, related_entries, entry_data, db_entry, entry_id
                )
    
    # Not part of an installment series
    if installments and installments > 1:
        return _create_installment_series_from_single(
            session, db_entry, entry_data, installments
        )
    
    # Regular update without installments
    for key, value in entry_data.items():
        setattr(db_entry, key, value)
        
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    
    return db_entry


def handle_entry_migration_or_update(
    session: Session,
    fixed_model: type[ModelT],
    unfixed_model: type[ModelT],
    entry_id: UUID,
    entry: SupportsModelDump,
    is_fixed: bool,
    installments: int | None,
    detail: str,
) -> ModelT:
    """
    Handle entry update with automatic migration between fixed/unfixed tables if needed.
    
    If the entry is in the wrong table (based on is_fixed), it will be migrated to the correct table.
    Otherwise, performs a normal update.
    """
    # Find the entry in either table and check if it needs migration
    db_entry, needs_migration = find_entry_in_both_tables(
        session, fixed_model, unfixed_model, entry_id, is_fixed, detail
    )
    
    if needs_migration:
        # Entry is in wrong table - migrate it
        target_model = fixed_model if is_fixed else unfixed_model
        
        # If it's an installment series, find all related entries in the old table
        if db_entry.installment and "/" in db_entry.installment:
            old_model = type(db_entry)
            related_entries = find_related_installments(session, old_model, db_entry)
            
            # Delete all old entries from the wrong table
            for old_entry in related_entries:
                session.delete(old_entry)
        else:
            # Just delete the single entry
            session.delete(db_entry)
        
        # Create new entry in the correct table with updated data
        new_entry = target_model.model_validate(entry)
        
        # Handle installments if provided
        if installments and installments > 1:
            db_entries = handle_installments_split(new_entry, installments)
            session.add_all(db_entries)
            session.commit()
            for entry_item in db_entries:
                session.refresh(entry_item)
            return db_entries[0]
        else:
            session.add(new_entry)
            session.commit()
            session.refresh(new_entry)
            return new_entry
    else:
        # Entry is in correct table - do normal update
        target_model = fixed_model if is_fixed else unfixed_model
        return update_entry(session, target_model, entry_id, entry, installments, detail)


def delete_entry(
        session: Session,
        model: type[ModelT],
        entry_id: UUID,
        detail: str) -> ModelT:
    db_entry = get_entry_or_404(session, model, entry_id, detail)

    if db_entry.installment:
        related_entries = find_related_installments(session, model, db_entry)

        for entry in related_entries:
            session.delete(entry)
        session.commit()
        return db_entry

    session.delete(db_entry)
    session.commit()

    return db_entry
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


def update_entry(
    session: Session,
    model: type[ModelT],
    entry_id: UUID,
    entry: SupportsModelDump,
    installments: int | None,
    detail: str,
    ) -> ModelT:
    db_entry = get_entry_or_404(session, model, entry_id, detail) 
    entry_data = entry.model_dump(exclude_unset=True)

    # Check if the entry is part of an installment series
    if db_entry.installment and "/" in db_entry.installment:
        # Find all related installments using ORIGINAL values (before updates)
        related_entries = find_related_installments(session, model, db_entry)
        
        if related_entries:
            # Get the current installment count
            current_installment_count = int(db_entry.installment.split("/")[1])
            
            # Check if we're changing the installment count
            if installments and installments > 1 and installments != current_installment_count:
                # CASE 1: Changing installment count - delete old, create new
                
                # Find the first installment to preserve its created_at
                first_entry = next((e for e in related_entries if e.installment.startswith("1/")), related_entries[0])
                original_created_at = first_entry.created_at
                
                # Calculate the ORIGINAL total amount BEFORE applying any updates
                # Example: 2 installments of $120 each = $240 total
                original_total_amount = db_entry.amount * current_installment_count
                
                # Check if amount is actually being changed (not just sent with same value)
                amount_is_changing = 'amount' in entry_data and entry_data['amount'] != db_entry.amount
                
                # Apply updates to db_entry
                for key, value in entry_data.items():
                    setattr(db_entry, key, value)
                
                # Calculate the total amount for the new installment series
                # If amount was NOT changed, redistribute the original total
                # If amount WAS changed, use the new amount for each installment
                if not amount_is_changing:
                    # No amount change - redistribute original total: (50 * 10) / 5 = 100 per installment
                    total_amount = original_total_amount
                else:
                    # Amount was changed - each installment gets this new amount
                    total_amount = db_entry.amount * installments
                
                # Delete all old installments
                for old_entry in related_entries:
                    session.delete(old_entry)
                
                # Create a new base entry with the updated data and total amount
                db_entry.amount = total_amount
                db_entry.created_at = original_created_at
                db_entry.installment = None  # Reset installment field before splitting
                
                # Create new installments
                db_entries = handle_installments_split(db_entry, installments)
                
                session.add_all(db_entries)
                session.commit()
                session.refresh(db_entries[0])
                
                return db_entries[0]
            else:
                # CASE 2: NOT changing installment count - update all related installments
                
                # Check if created_at is being updated - need to recalculate all dates
                if 'created_at' in entry_data:
                    # Parse which installment this is (e.g., "3/5" -> installment 3)
                    installment_number = int(db_entry.installment.split("/")[0])
                    new_created_at = entry_data['created_at']
                    
                    # Calculate what the first installment's date should be
                    # by going back (installment_number - 1) months
                    first_installment_date = add_months(new_created_at, -(installment_number - 1))
                    
                    # Update ALL related installments with recalculated dates and other fields
                    for related_entry in related_entries:
                        # Get this entry's installment number
                        entry_installment_num = int(related_entry.installment.split("/")[0])
                        
                        # Calculate the correct date for this installment
                        related_entry.created_at = add_months(first_installment_date, entry_installment_num - 1)
                        
                        # Apply other updates (except created_at which we just set)
                        for key, value in entry_data.items():
                            if key != 'created_at':
                                setattr(related_entry, key, value)
                        
                        session.add(related_entry)
                else:
                    # No created_at change - just update all related installments with same values
                    for related_entry in related_entries:
                        for key, value in entry_data.items():
                            setattr(related_entry, key, value)
                        session.add(related_entry)
                
                session.commit()
                
                # Refresh and return the original entry we were asked to update
                session.refresh(db_entry)
                return db_entry
    
    # Not part of an installment series
    if installments and installments > 1:
        # Create new installment series from a single entry
        for key, value in entry_data.items():
            setattr(db_entry, key, value)
            
        db_entries = handle_installments_split(db_entry, installments)
        
        session.add_all(db_entries)
        session.commit()
        session.refresh(db_entries[0])
        
        return db_entries[0]
    
    # Regular update without installments
    for key, value in entry_data.items():
        setattr(db_entry, key, value)
        
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    
    return db_entry


def delete_entry(session: Session, model: type[ModelT], entry_id: UUID, detail: str) -> ModelT:
    db_entry = get_entry_or_404(session, model, entry_id, detail)
    session.delete(db_entry)
    session.commit()
    return db_entry
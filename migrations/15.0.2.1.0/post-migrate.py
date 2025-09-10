# Copyright 2025
# Odoo 15.0 migration: adjust FK to cascade on pos.paie.periode.ligne.vendeur_id
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # Ensure DB-level FK uses ON DELETE CASCADE for periode line -> vendeur
    # The constraint name mentioned: pos_paie_periode_ligne_vendeur_id_fkey
    # Drop and recreate with CASCADE if exists.
    cr.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints tc
                WHERE tc.constraint_name = 'pos_paie_periode_ligne_vendeur_id_fkey'
            ) THEN
                ALTER TABLE pos_paie_periode_ligne DROP CONSTRAINT pos_paie_periode_ligne_vendeur_id_fkey;
            END IF;
        END$$;
        """
    )
    cr.execute(
        """
        ALTER TABLE pos_paie_periode_ligne
        ADD CONSTRAINT pos_paie_periode_ligne_vendeur_id_fkey
        FOREIGN KEY (vendeur_id)
        REFERENCES pos_caisse_vendeur(id)
        ON DELETE CASCADE
        DEFERRABLE INITIALLY DEFERRED;
        """
    )

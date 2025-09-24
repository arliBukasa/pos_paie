from odoo import models, fields, api
from datetime import datetime
from dateutil.relativedelta import relativedelta
import logging

class PaieVendeur(models.Model):
    _name = 'pos.paie.vendeur'
    _description = 'Paie Vendeur'
    _inherits = {'pos.caisse.vendeur': 'vendor_id'}

    vendor_id = fields.Many2one('pos.caisse.vendeur', string='Vendeur', required=True, ondelete='cascade')
    date_debut = fields.Date(
        'Période du',
        default=lambda self: fields.Date.to_date(fields.Date.context_today(self)).replace(day=1),
    )
    date_fin = fields.Date(
        'Période au',
        default=lambda self: fields.Date.to_date(fields.Date.context_today(self)) + relativedelta(day=31),
    )

    total_commandes = fields.Float('Total commandes', compute='_compute_totaux', store=False)
    montant_paye = fields.Float('Montant payé')
    pourcentage = fields.Float('Pourcentage retenu', default=25.0)
    date_paiement = fields.Date('Date de paiement')
    commande_ids = fields.One2many('pos.paie.commande', 'paie_id', string='Commandes')

    # Auto fill commandes when selecting vendor or changing dates
    @api.onchange('vendor_id')
    def _onchange_vendor(self):
        if not self.vendor_id:
            self.commande_ids = [(5, 0, 0)]
            self.total_commandes = 0.0
            self.montant_paye = 0.0
            return
        # Ensure default month if empty
        if not self.date_debut:
            self.date_debut = fields.Date.to_date(fields.Date.context_today(self)).replace(day=1)
        if not self.date_fin:
            self.date_fin = fields.Date.to_date(fields.Date.context_today(self)) + relativedelta(day=31)
        # Sync pourcentage from vendor if available
        if getattr(self.vendor_id, 'pourcentage_commission', False):
            self.pourcentage = self.vendor_id.pourcentage_commission
        self._populate_commandes_for_period()
        self.calculer_paie()

    @api.onchange('date_debut', 'date_fin')
    def _onchange_dates(self):
        if self.vendor_id and self.date_debut and self.date_fin:
            # Normalize if reversed
            if self.date_debut > self.date_fin:
                self.date_debut, self.date_fin = self.date_fin, self.date_debut
            self._populate_commandes_for_period()
            self.calculer_paie()

    def _populate_commandes_for_period(self):
        self.ensure_one()
        Cmd = self.env['pos.caisse.commande']
        domain = [('client_card', '=', self.carte_numero), ('state', '!=', 'annule')]
        if self.date_debut:
            start_dt = datetime.combine(self.date_debut, datetime.min.time())
            domain.append(('date', '>=', fields.Datetime.to_string(start_dt)))
        if self.date_fin:
            end_dt = datetime.combine(self.date_fin, datetime.max.time())
            domain.append(('date', '<=', fields.Datetime.to_string(end_dt)))
        commandes = Cmd.search(domain)
        lines = [(0, 0, {
            'commande_id': c.id,
            'montant': c.total,
            'date': fields.Date.to_date(c.date) if c.date else False,
        }) for c in commandes]
        self.commande_ids = [(5, 0, 0)] + lines

    @api.depends('commande_ids.montant')
    def _compute_totaux(self):
        for rec in self:
            rec.total_commandes = sum(rec.commande_ids.mapped('montant')) if rec.commande_ids else 0.0

    def calculer_paie(self):
        for rec in self:
            # Total BP à retrancher
            total_bp = sum(
                line.montant for line in rec.commande_ids
                if getattr(line.commande_id, 'type_paiement', False) == 'bp'
            )
            rec.montant_paye = (rec.total_commandes * (rec.pourcentage/100 or 0.0)) - total_bp

    def action_prepare_sortie_caisse(self):
        self.ensure_one()
        self.calculer_paie()
        motif = f"Paie vendeur {self.display_name}"
        if self.date_debut and self.date_fin:
            motif += f" ({self.date_debut} → {self.date_fin})"
        ctx = {
            'default_type': 'sortie',
            'default_montant': self.montant_paye,
            'default_motif': motif,
        }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sortie de Caisse',
            'res_model': 'pos.caisse.mouvement',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }

    def action_open_wizard(self):
        self.ensure_one()
        action = self.env.ref('pos_paie.action_pos_paie_wizard').read()[0]
        ctx = action.get('context') or {}
        if isinstance(ctx, str):
            ctx = {}
        ctx.update({'default_vendeur_id': self.vendor_id.id})
        action['context'] = ctx
        return action

class PaieCommande(models.Model):
    _name = 'pos.paie.commande'
    _description = 'Commande pour paie vendeur'

    paie_id = fields.Many2one('pos.paie.vendeur', string='Paie vendeur')
    vendeur_card = fields.Char(related='paie_id.carte_numero', store=False)
    commande_id = fields.Many2one(
        'pos.caisse.commande',
        string='Commande',
        domain="[('client_card', '=', vendeur_card), ('state', '!=', 'annule')]",
    )
    type_paiement = fields.Selection(related='commande_id.type_paiement', store=False)
    montant = fields.Float('Montant')
    date = fields.Date('Date')

    _sql_constraints = [
        ('paie_commande_unique', 'unique(paie_id, commande_id)', 'Cette commande est déjà incluse dans cette paie.'),
    ]

    @api.onchange('commande_id')
    def _onchange_commande_id(self):
        for rec in self:
            if rec.commande_id:
                rec.montant = rec.commande_id.total
                rec.date = fields.Date.to_date(rec.commande_id.date) if rec.commande_id.date else False

class PosPaieWizard(models.TransientModel):
    _name = 'pos.paie.wizard'
    _description = 'Assistant Paie Vendeur (basé sur pos.caisse.commande)'

    vendeur_id = fields.Many2one('pos.caisse.vendeur', string='Vendeur', required=True)
    date_debut = fields.Date('Du', required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_fin = fields.Date('Au', required=True, default=lambda self: fields.Date.context_today(self) + relativedelta(day=31))
    pourcentage = fields.Float('Pourcentage retenu', default=25.0)

    total_commandes = fields.Float('Total commandes', readonly=True)
    montant_net = fields.Float('Montant à payer', readonly=True)

    @api.onchange('vendeur_id')
    def _onchange_vendeur_id(self):
        if self.vendeur_id and getattr(self.vendeur_id, 'pourcentage_commission', False):
            self.pourcentage = self.vendeur_id.pourcentage_commission
        self._recompute_totaux()

    @api.onchange('date_debut', 'date_fin', 'pourcentage')
    def _onchange_dates_or_pourcentage(self):
        self._recompute_totaux()

    def _recompute_totaux(self):
        if not (self.vendeur_id and self.date_debut and self.date_fin):
            self.total_commandes = 0.0
            self.montant_net = 0.0
            return
        start_dt = datetime.combine(self.date_debut, datetime.min.time())
        end_dt = datetime.combine(self.date_fin, datetime.max.time())
        domain = [
            ('client_card', '=', self.vendeur_id.carte_numero),
            ('state', '!=', 'annule'),
            ('date', '>=', fields.Datetime.to_string(start_dt)),
            ('date', '<=', fields.Datetime.to_string(end_dt)),
        ]
        commandes = self.env['pos.caisse.commande'].search(domain)
        total_all = sum(commandes.mapped('total')) if commandes else 0.0
        total_bp = sum(c.total for c in commandes if getattr(c, 'type_paiement', False) == 'bp') if commandes else 0.0
        self.total_commandes = total_all
        self.montant_net = (total_all * (self.pourcentage or 0.0)) - total_bp

    def action_prepare_sortie_caisse(self):
        self.ensure_one()
        self._recompute_totaux()
        motif = f"Paie vendeur {self.vendeur_id.display_name}"
        if self.date_debut and self.date_fin:
            motif += f" ({self.date_debut} → {self.date_fin})"
        ctx = {
            'default_type': 'sortie',
            'default_montant': self.montant_net,
            'default_motif': motif,
        }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sortie de Caisse',
            'res_model': 'pos.caisse.mouvement',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }


class PosPaiePeriode(models.Model):
    _name = 'pos.paie.periode'
    _description = 'Période de paie (agrégée par vendeur)'
    _order = 'date_debut desc, id desc'

    name = fields.Char('Nom', required=True, default=lambda self: self._default_name())
    date_debut = fields.Date('Du', required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_fin = fields.Date('Au', required=True, default=lambda self: fields.Date.context_today(self) + relativedelta(day=31))
    ligne_ids = fields.One2many('pos.paie.periode.ligne', 'periode_id', string='Lignes (vendeurs)')

    total_commandes = fields.Float('Total commandes', compute='_compute_totaux', store=False)
    total_cash = fields.Float('Total cash', compute='_compute_totaux', store=False)
    total_bp = fields.Float('Total BP', compute='_compute_totaux', store=False)
    commission_total = fields.Float('Commission totale', compute='_compute_totaux', store=False)
    montant_net_total = fields.Float('Montant net total', compute='_compute_totaux', store=False)

    def _default_name(self):
        today = fields.Date.context_today(self)
        start = today.replace(day=1)
        end = today + relativedelta(day=31)
        return f"Paie {start} → {end}"

    @api.depends('ligne_ids.total_commandes', 'ligne_ids.total_bp', 'ligne_ids.commission', 'ligne_ids.montant_net')
    def _compute_totaux(self):
        for rec in self:
            rec.total_commandes = sum(rec.ligne_ids.mapped('total_commandes'))
            rec.total_bp = sum(rec.ligne_ids.mapped('total_bp'))
            rec.total_cash = rec.total_commandes - rec.total_bp
            rec.commission_total = sum(rec.ligne_ids.mapped('commission'))
            rec.montant_net_total = sum(rec.ligne_ids.mapped('montant_net'))

    def action_recompute(self):
        for rec in self:
            rec._recompute_lines()
        return True
    def _recompute(self):
        for rec in self:
            rec._recompute_lines()
        return True

    def _recompute_lines(self):
        self.ensure_one()
        # Clear existing lines
        self.ligne_ids = [(5, 0, 0)]
        Cmd = self.env['pos.caisse.commande'].sudo()
        V = self.env['pos.caisse.vendeur'].sudo()
        # Build date range
        start_dt = datetime.combine(self.date_debut, datetime.min.time()) if self.date_debut else None
        end_dt = datetime.combine(self.date_fin, datetime.max.time()) if self.date_fin else None
        domain = [('state', '!=', 'annule')]
        if start_dt:
            domain.append(('date', '>=', fields.Datetime.to_string(start_dt)))
        if end_dt:
            domain.append(('date', '<=', fields.Datetime.to_string(end_dt)))
        commandes = Cmd.search(domain)
        if not commandes:
            return
        # Group by client_card
        cards = set(c.client_card for c in commandes if getattr(c, 'client_card', False))
        vendeurs = V.search([('carte_numero', 'in', list(cards))]) if cards else V.browse([])
        vend_by_card = {v.carte_numero: v for v in vendeurs}
        # Aggregate per card
        by_card = {}
        for c in commandes:
            card = getattr(c, 'client_card', False)
            if not card:
                continue
            agg = by_card.setdefault(card, {'nb': 0, 'total': 0.0, 'total_bp': 0.0})
            agg['nb'] += 1
            agg['total'] += c.total
            if getattr(c, 'type_paiement', False) == 'bp':
                agg['total_bp'] += c.total
        # Create lines
        lines_vals = []
        for card, vals in by_card.items():
            v = vend_by_card.get(card)
            if not v:
                continue
            pourc = (getattr(v, 'pourcentage_commission', 25) or 25) / 100.0
            logging.info(f"================= Vendeur {v.id} ({v.display_name}) - Nb commandes: {vals['nb']}, Total: {vals['total']}, Total BP: {vals['total_bp']}, Pourcentage: {pourc}%")
            commission = vals['total'] * pourc
            logging.info(f"Calculating commission for vendeur {v.id}: {commission}")
            montant_net = commission - vals['total_bp']
            lines_vals.append((0, 0, {
                'vendeur_id': v.id,
                'nb_commandes': vals['nb'],
                'total_commandes': vals['total'],
                'total_bp': vals['total_bp'],
                'pourcentage': pourc,
                'commission': commission,
                'montant_net': montant_net,
            }))
        if lines_vals:
            self.ligne_ids = lines_vals

    # surcharge de la methode create pour forcer le recalcul des lignes
    @api.model
    def create(self, vals):
        rec = super().create(vals)
        rec._recompute()
        return rec


class PosPaiePeriodeLigne(models.Model):
    _name = 'pos.paie.periode.ligne'
    _description = 'Ligne de paie par vendeur (période)'
    _order = 'total_commandes desc'

    periode_id = fields.Many2one('pos.paie.periode', string='Période', required=True, ondelete='cascade', index=True)
    vendeur_id = fields.Many2one(
        'pos.caisse.vendeur',
        string='Vendeur',
        required=True,
        index=True,
        ondelete='cascade',  # If a vendor is deleted, remove the aggregated payroll line to avoid FK blocks
    )
    nb_commandes = fields.Integer('Nb commandes', default=0)
    total_commandes = fields.Float('Total commandes', default=0.0)
    total_bp = fields.Float('Total BP', default=0.0)
    pourcentage = fields.Float('Pourcentage', default=0.25)
    commission = fields.Float('Commission', default=0.0)
    montant_net = fields.Float('Montant net', default=0.0)

    _sql_constraints = [
        ('periode_vendeur_unique', 'unique(periode_id, vendeur_id)', 'Ce vendeur est déjà présent dans cette période.'),
    ]

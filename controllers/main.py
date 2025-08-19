from odoo import http, fields
from odoo.http import request
from datetime import datetime
from collections import defaultdict

class PosPaieApi(http.Controller):
    @http.route(['/api/pos_paie/vendeurs'], type='json', auth='user', methods=['GET', 'POST'], csrf=False)
    def get_vendeurs(self, **payload):
        # Optional period and totals
        date_debut = payload.get('date_debut')
        date_fin = payload.get('date_fin')
        limit = int(payload.get('limit') or 50)
        with_totaux = bool(payload.get('with_totaux'))
        pourcentage = payload.get('pourcentage')
        if with_totaux:
            try:
                # API contract: decimal fraction (0.25 == 25%)
                pourcentage = float(pourcentage if pourcentage is not None else 0.25)
            except Exception:
                return {'status': 'error', 'message': 'pourcentage invalide'}
        Vendor = request.env['pos.caisse.vendeur'].sudo()
        vendors = Vendor.search([], limit=limit)
        result = []
        start_dt = end_dt = None
        if date_debut:
            start_dt = datetime.combine(fields.Date.from_string(date_debut), datetime.min.time())
        if date_fin:
            end_dt = datetime.combine(fields.Date.from_string(date_fin), datetime.max.time())
        Cmd = request.env['pos.caisse.commande'].sudo()
        for v in vendors:
            # Always compute BP-only aggregates for compatibility
            domain_bp = [('client_card', '=', v.carte_numero), ('type_paiement', '=', 'bp'), ('state', '!=', 'annule')]
            if start_dt:
                domain_bp.append(('date', '>=', fields.Datetime.to_string(start_dt)))
            if end_dt:
                domain_bp.append(('date', '<=', fields.Datetime.to_string(end_dt)))
            cmds_bp = Cmd.search(domain_bp)
            total_bp = sum(cmds_bp.mapped('total')) if cmds_bp else 0.0
            entry = {
                'id': v.id,
                'name': v.display_name,
                'carte_numero': v.carte_numero,
                'total_bp': total_bp,
                'nb_commandes': len(cmds_bp),
            }
            if with_totaux:
                domain_all = [('client_card', '=', v.carte_numero), ('state', '!=', 'annule')]
                if start_dt:
                    domain_all.append(('date', '>=', fields.Datetime.to_string(start_dt)))
                if end_dt:
                    domain_all.append(('date', '<=', fields.Datetime.to_string(end_dt)))
                cmds_all = Cmd.search(domain_all)
                total_all = sum(cmds_all.mapped('total')) if cmds_all else 0.0
                commission = total_all * (pourcentage or 0.0)
                montant_net = commission - total_bp
                entry.update({
                    'total_commandes': total_all,
                    'commission': commission,
                    'montant_net': montant_net,
                })
            result.append(entry)
        return {'status': 'success', 'vendeurs': result, 'date_debut': date_debut, 'date_fin': date_fin}

    @http.route('/api/pos_paie/calculer', type='json', auth='user', methods=['POST'], csrf=False)
    def calculer_paie(self, **payload):
        vendeur_card = payload.get('vendeur_card')
        date_debut = payload.get('date_debut')
        date_fin = payload.get('date_fin')
        pourcentage = payload.get('pourcentage')
        if pourcentage is None:
            pourcentage = 0.25  # default 25% as a decimal fraction
        try:
            pourcentage = float(pourcentage)
        except Exception:
            return {'status': 'error', 'message': 'pourcentage invalide'}
        if not (vendeur_card and date_debut and date_fin):
            return {'status': 'error', 'message': 'vendeur_card, date_debut et date_fin sont requis'}
        try:
            start_dt = datetime.combine(fields.Date.from_string(date_debut), datetime.min.time())
            end_dt = datetime.combine(fields.Date.from_string(date_fin), datetime.max.time())
        except Exception:
            return {'status': 'error', 'message': 'Format de date invalide (YYYY-MM-DD attendu)'}
        Cmd = request.env['pos.caisse.commande'].sudo()
        domain_all = [
            ('client_card', '=', vendeur_card),
            ('state', '!=', 'annule'),
            ('date', '>=', fields.Datetime.to_string(start_dt)),
            ('date', '<=', fields.Datetime.to_string(end_dt)),
        ]
        commandes = Cmd.search(domain_all)
        total_all = sum(commandes.mapped('total')) if commandes else 0.0
        total_bp = sum(c.total for c in commandes if getattr(c, 'type_paiement', False) == 'bp') if commandes else 0.0
        commission = total_all * (pourcentage or 0.0)
        montant_net = commission - total_bp
        # Prepare commandes list
        commandes_out = [{
            'id': c.id,
            'name': c.name,
            'date': fields.Date.to_date(c.date).isoformat() if c.date else None,
            'total': c.total,
            'type_paiement': c.type_paiement,
        } for c in commandes]
        # Breakdown by day
        daily = defaultdict(lambda: {'total': 0.0, 'total_bp': 0.0, 'nb': 0})
        for c in commandes:
            d = fields.Date.to_date(c.date).isoformat() if c.date else None
            if not d:
                continue
            daily[d]['total'] += c.total
            daily[d]['nb'] += 1
            if c.type_paiement == 'bp':
                daily[d]['total_bp'] += c.total
        breakdown_jour = [
            {'date': d, 'total': vals['total'], 'total_bp': vals['total_bp'], 'nb': vals['nb']}
            for d, vals in sorted(daily.items())
        ]
        return {
            'status': 'success',
            'vendeur_card': vendeur_card,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'pourcentage': pourcentage,
            'total_commandes': total_all,
            'total_bp': total_bp,
            'commission': commission,
            'montant_net': montant_net,
            'commandes': commandes_out,
            'breakdown_jour': breakdown_jour,
        }

    @http.route('/api/pos_paie/rapport', type='json', auth='user', methods=['POST'], csrf=False)
    def rapport(self, **payload):
        # Alias de calculer avec retour allégé (sans commandes), adapté aux tableaux de bord
        payload = payload or {}
        res = self.calculer_paie(**payload)
        if res.get('status') != 'success':
            return res
        keys = ['vendeur_card', 'date_debut', 'date_fin', 'pourcentage', 'total_commandes', 'total_bp', 'commission', 'montant_net', 'breakdown_jour']
        return {k: res[k] for k in keys if k in res} | {'status': 'success'}

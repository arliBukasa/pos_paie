from odoo import http, fields
from odoo.http import request
from datetime import datetime
from collections import defaultdict

class PosPaieApi(http.Controller):
    @http.route(['/api/pos_paie/vendeurs'], type='json', auth='user', methods=['GET', 'POST'], csrf=False)
    def get_vendeurs(self, **payload):
        # Accept both plain JSON and JSON-RPC envelope
        params = http.request.jsonrequest or payload or {}
        if isinstance(params, dict) and 'params' in params and isinstance(params.get('params'), dict):
            params = params['params']
        # Optional period and totals
        date_debut = params.get('date_debut')
        date_fin = params.get('date_fin')
        limit = int(params.get('limit') or 50)
        with_totaux = bool(params.get('with_totaux'))
        pourcentage = params.get('pourcentage')
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
                'total_bp': int(total_bp),
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
                    'total_commandes': int(total_all),
                    'commission': int(commission),
                    'montant_net': int(montant_net),
                })
            result.append(entry)

        # Odoo will wrap this into a JSON-RPC response automatically (type='json')
        return {
            'status': 'success',
            'vendeurs': result,
            'date_debut': date_debut,
            'date_fin': date_fin,
        }

    @http.route('/api/pos_paie/calculer', type='json', auth='user', methods=['POST'], csrf=False)
    def calculer_paie(self, **payload):
        params = http.request.jsonrequest or payload or {}
        if isinstance(params, dict) and 'params' in params and isinstance(params.get('params'), dict):
            params = params['params']
        vendeur_card = params.get('vendeur_card')
        date_debut = params.get('date_debut')
        date_fin = params.get('date_fin')
        pourcentage = params.get('pourcentage')
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
            'total': int(c.total),
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
            {'date': d, 'total': int(vals['total']), 'total_bp': int(vals['total_bp']), 'nb': vals['nb']}
            for d, vals in sorted(daily.items())
        ]
        return {
            'status': 'success',
            'vendeur_card': vendeur_card,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'pourcentage': pourcentage,
            'total_commandes': int(total_all),
            'total_bp': int(total_bp),
            'commission': int(commission),
            'montant_net': int(montant_net),
            'commandes': commandes_out,
            'breakdown_jour': breakdown_jour,
        }

    @http.route('/api/pos_paie/rapport', type='json', auth='user', methods=['POST'], csrf=False)
    def rapport(self, **payload):
        # Alias de calculer avec retour allégé (sans commandes), adapté aux tableaux de bord
        params = http.request.jsonrequest or payload or {}
        if isinstance(params, dict) and 'params' in params and isinstance(params.get('params'), dict):
            params = params['params']
        res = self.calculer_paie(**params)
        if res.get('status') != 'success':
            return res
        keys = ['vendeur_card', 'date_debut', 'date_fin', 'pourcentage', 'total_commandes', 'total_bp', 'commission', 'montant_net', 'breakdown_jour']
        return {k: res[k] for k in keys if k in res} | {'status': 'success'}

    @http.route('/api/pos_paie/totaux', type='json', auth='user', methods=['GET'], csrf=False)
    def totaux_legacy(self, **kwargs):
        # Legacy shape for compatibility: list of vendeurs with aggregated amounts
        pourcentage = 0.25
        Vendor = request.env['pos.caisse.vendeur'].sudo()
        Cmd = request.env['pos.caisse.commande'].sudo()
        vendeurs = []
        for v in Vendor.search([]):
            domain = [('client_card', '=', v.carte_numero), ('state', '!=', 'annule')]
            cmds = Cmd.search(domain)
            total_all = sum(cmds.mapped('total')) if cmds else 0.0
            total_bp = sum(c.total for c in cmds if getattr(c, 'type_paiement', False) == 'bp') if cmds else 0.0
            commission = total_all * pourcentage
            net = commission - total_bp
            vendeurs.append({
                'numero_carte': v.carte_numero,
                'nom': v.display_name,
                'total_commandes_fc': int(total_all),
                'retenue_fc': int(commission),
                'a_payer_fc': int(net),
            })
        return {'status': 'success', 'vendeurs': vendeurs}

    @http.route('/api/pos_paie/payer/<string:numeroCarte>', type='json', auth='user', methods=['POST'], csrf=False)
    def payer_vendeur(self, numeroCarte, **payload):
        # Minimal stub: mark as acknowledged. Could be extended to create a sortie de caisse.
        if not numeroCarte:
            return {'status': 'error', 'message': 'numeroCarte manquant'}
        return {'status': 'success'}

    @http.route('/api/pos_paie/periode/create', type='json', auth='user', methods=['POST'], csrf=False)
    def create_periode(self, **payload):
        # Allow paie user or manager to create periods
        user = request.env.user
        if not (user.has_group('pos_paie.group_pos_paie_manager') or user.has_group('pos_paie.group_pos_paie_user')):
            return {'status': 'error', 'message': "Accès refusé"}
        params = http.request.jsonrequest or payload or {}
        if isinstance(params, dict) and 'params' in params and isinstance(params.get('params'), dict):
            params = params['params']
        date_debut = params.get('date_debut')
        date_fin = params.get('date_fin')
        name = params.get('name')
        if not (date_debut and date_fin):
            return {'status': 'error', 'message': 'date_debut et date_fin sont requis'}
        try:
            dd = fields.Date.from_string(date_debut)
            df = fields.Date.from_string(date_fin)
        except Exception:
            return {'status': 'error', 'message': 'Format de date invalide (YYYY-MM-DD attendu)'}
        if not name:
            name = f"Paie {date_debut} → {date_fin}"
        Per = request.env['pos.paie.periode'].sudo()
        periode = Per.create({
            'name': name,
            'date_debut': dd,
            'date_fin': df,
        })
        # Recompute aggregate lines
        periode.action_recompute()
        # Compute totals (cast to int FC for client)
        total_cmd = sum(periode.ligne_ids.mapped('total_commandes')) if periode.ligne_ids else 0.0
        total_bp = sum(periode.ligne_ids.mapped('total_bp')) if periode.ligne_ids else 0.0
        commission_total = sum(periode.ligne_ids.mapped('commission')) if periode.ligne_ids else 0.0
        montant_net_total = sum(periode.ligne_ids.mapped('montant_net')) if periode.ligne_ids else 0.0
        return {
            'status': 'success',
            'id': periode.id,
            'name': periode.name,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'nb_vendeurs': len(periode.ligne_ids),
            'total_commandes': int(total_cmd),
            'total_bp': int(total_bp),
            'commission_total': int(commission_total),
            'montant_net_total': int(montant_net_total),
        }

    @http.route('/api/pos_paie/periodes', type='json', auth='user', methods=['GET', 'POST'], csrf=False)
    def list_periodes(self, **payload):
        params = http.request.jsonrequest or payload or {}
        if isinstance(params, dict) and 'params' in params and isinstance(params.get('params'), dict):
            params = params['params']
        limit = int(params.get('limit') or 50)
        offset = int(params.get('offset') or 0)
        Per = request.env['pos.paie.periode'].sudo()
        total = Per.search_count([])
        periodes = Per.search([], limit=limit, offset=offset, order='date_debut desc, id desc')
        data = [{
            'id': p.id,
            'name': p.name,
            'date_debut': fields.Date.to_string(p.date_debut) if p.date_debut else None,
            'date_fin': fields.Date.to_string(p.date_fin) if p.date_fin else None,
            'nb_vendeurs': len(p.ligne_ids),
            'total_commandes': int(sum(p.ligne_ids.mapped('total_commandes')) if p.ligne_ids else 0.0),
            'total_bp': int(sum(p.ligne_ids.mapped('total_bp')) if p.ligne_ids else 0.0),
            'commission_total': int(sum(p.ligne_ids.mapped('commission')) if p.ligne_ids else 0.0),
            'montant_net_total': int(sum(p.ligne_ids.mapped('montant_net')) if p.ligne_ids else 0.0),
            'paies': [{'id': paie.vendeur_id.id, 'name': paie.vendeur_id.name, 'carte_numero': paie.vendeur_id.carte_numero, 'nb_commandes': paie.nb_commandes, 'total_commandes': paie.total_commandes, 'total_bp': paie.total_bp, 'commission': paie.commission, 'montant_net': paie.montant_net} for paie in p.ligne_ids] if p.ligne_ids else [],
        } for p in periodes]
        return {'status': 'success', 'periodes': data, 'total': total, 'offset': offset, 'limit': limit}

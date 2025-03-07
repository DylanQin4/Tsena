from flask import Flask, request, jsonify, render_template
import pyodbc
from datetime import datetime

app = Flask(__name__)

def get_db_connection():
    conn = pyodbc.connect(r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=H:\IT\S6\Rattrapage\Tsena\tsena.accdb')
    return conn

@app.route('/paiement/<int:box_id>', methods=['GET', 'POST'])
def paiement(box_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Recuperer les informations du box
    cursor.execute("SELECT id, numero FROM box WHERE id = ?", (box_id,))
    box = cursor.fetchone()
    if box is None:
        conn.close()
        return "Box non trouve", 404

    if request.method == 'GET':
        conn.close()
        return render_template('paiement.html', box=box)
    else:
        # Traitement du formulaire de paiement
        try:
            montant = float(request.form.get('montant', 0))
            date_paiement_str = request.form.get('date_paiement')
            date_paiement = datetime.strptime(date_paiement_str, '%Y-%m-%d').date() if date_paiement_str else datetime.today().date()
        except Exception as e:
            conn.close()
            return render_template('paiement.html', box=box, error="Erreur dans les donnees saisies: " + str(e))
        
        if montant <= 0:
            conn.close()
            return render_template('paiement.html', box=box, error="Le montant doit etre superieur e 0")
        
        # Recuperer le proprietaire_id depuis un contrat associe a ce box
        cursor.execute("SELECT TOP 1 proprietaire_id FROM contrat WHERE box_id = ? ORDER BY date_debut DESC", (box_id,))
        row = cursor.fetchone()
        if row is None:
            conn.close()
            return render_template('paiement.html', box=box, error="Aucun contrat trouve pour ce box.")
        proprietaire_id = row[0]

        # Calculer le debut du mois de paiement
        payment_month_start = datetime(date_paiement.year, date_paiement.month, 1).date()

        # Requete pour obtenir les factures en retard (pour les boxes differents du box courant)
        query_overdue = """
        SELECT 
            f.id, 
            f.montant_total, 
            f.mois, 
            f.annee,
            (f.montant_total - IIf(IsNull(SUM(p.montant)), 0, SUM(p.montant))) AS montant_restant
        FROM facture f
        LEFT JOIN paiement p ON f.id = p.facture_id
        WHERE f.contrat_id IN (
            SELECT id FROM contrat WHERE proprietaire_id = ? AND box_id <> ?
        )
          AND DateSerial(f.annee, f.mois, 1) < ?
        GROUP BY f.id, f.montant_total, f.mois, f.annee
        HAVING (f.montant_total - IIf(IsNull(SUM(p.montant)), 0, SUM(p.montant))) > 0
        ORDER BY f.annee, f.mois
        """
        cursor.execute(query_overdue, (proprietaire_id, box_id, payment_month_start))
        overdue_factures = cursor.fetchall()

        # Requete pour obtenir les factures du box (factures dont le mois est superieur ou egal au mois de paiement)
        query_current = """
        SELECT 
            f.id, 
            f.montant_total, 
            f.mois, 
            f.annee,
            (f.montant_total - IIf(IsNull(SUM(p.montant)), 0, SUM(p.montant))) AS montant_restant
        FROM facture f
        LEFT JOIN paiement p ON f.id = p.facture_id
        WHERE f.contrat_id IN (
            SELECT id FROM contrat WHERE proprietaire_id = ? AND box_id = ?
        )
          AND DateSerial(f.annee, f.mois, 1) >= ?
        GROUP BY f.id, f.montant_total, f.mois, f.annee
        HAVING (f.montant_total - IIf(IsNull(SUM(p.montant)), 0, SUM(p.montant))) > 0
        ORDER BY f.annee, f.mois
        """
        cursor.execute(query_current, (proprietaire_id, box_id, payment_month_start))
        current_factures = cursor.fetchall()

        # Combiner les factures : d'abord les factures en retard, puis celles du box courant
        unpaid_factures = list(overdue_factures) + list(current_factures)

        if not unpaid_factures:
            conn.close()
            return render_template('paiement.html', box=box, message="Aucune facture non payee pour ce proprietaire.")

        paiement_details = []
        remaining_payment = montant

        # Allouer le paiement sur chaque facture dans l'ordre
        for facture in unpaid_factures:
            facture_id = facture[0]
            montant_total = facture[1]
            mois_facture = facture[2]
            annee_facture = facture[3]
            montant_restant = facture[4]

            if remaining_payment <= 0:
                break

            # Convertir le montant_restant en float
            payment_for_facture = min(remaining_payment, float(montant_restant))
            cursor.execute("""
                INSERT INTO paiement (date_paiement, montant, facture_id)
                VALUES (?, ?, ?)
            """, (date_paiement, payment_for_facture, facture_id))
            conn.commit()

            paiement_details.append({
                "facture_id": facture_id,
                "mois": mois_facture,
                "annee": annee_facture,
                "montant_paye": payment_for_facture
            })

            remaining_payment -= payment_for_facture

        conn.close()
        message = "Paiement enregistre avec succes."
        return render_template('paiement.html', box=box, message=message, paiement_details=paiement_details)
    
@app.route('/', methods=['GET', 'POST'])
def index():
    mois = request.args.get('mois', 1, type=int)
    annee = request.args.get('annee', 2024, type=int)
    
    # Construire une date cible e partir de l'annee et du mois
    target_date = datetime(annee, mois, 1).date()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT 
        b.id, 
        b.numero, 
        b.longueur, 
        b.largeur,
        (SELECT nom FROM tsena WHERE id = b.tsena_id) AS tsena_nom,
        (SELECT TOP 1 prix_m2 
         FROM historique_prix 
         WHERE tsena_id = b.tsena_id AND date_creation <= ?
         ORDER BY date_creation DESC
        ) AS prix_m2,
        (
         SELECT f.montant_total - IIf(IsNull((SELECT SUM(p.montant) FROM paiement p WHERE p.facture_id = f.id)), 0, (SELECT SUM(p.montant) FROM paiement p WHERE p.facture_id = f.id))
         FROM facture f
         WHERE f.contrat_id IN (SELECT id FROM contrat WHERE box_id = b.id)
           AND f.mois = ? AND f.annee = ?
        ) AS montant_restant,
        (
         SELECT f.montant_total
         FROM facture f
         WHERE f.contrat_id IN (SELECT id FROM contrat WHERE box_id = b.id)
           AND f.mois = ? AND f.annee = ?
        ) AS montant_total
    FROM box b
    """
    cursor.execute(query, (target_date, mois, annee, mois, annee))
    boxes = cursor.fetchall()
    conn.close()

    # Organiser les boxes par Tsena
    tsena_boxes = {}
    for box in boxes:
        tsena_nom = box[4]  # Le nom du tsena
        if tsena_nom not in tsena_boxes:
            tsena_boxes[tsena_nom] = []
        tsena_boxes[tsena_nom].append(box)
    
    return render_template('index.html', boxes=boxes, tsena_boxes=tsena_boxes, mois=mois, annee=annee)

def contract_exists(box_id):
    """Verifie s'il existe deje un contrat actif pour le box (date_fin >= aujourd'hui)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.today().date()
    cursor.execute("SELECT id FROM contrat WHERE box_id = ? AND date_fin >= ?", (box_id, today))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def generate_invoices(contract_id, box_id, date_debut, date_fin):
    """Genere une facture pour chaque mois entre date_debut et date_fin pour le contrat donne."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Recuperer la surface du box et son tsena_id
    cursor.execute("SELECT longueur, largeur, tsena_id FROM box WHERE id = ?", (box_id,))
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return "Box introuvable."
    longueur, largeur, tsena_id = row
    surface = longueur * largeur

    current_date = date_debut
    while current_date <= date_fin:
        # Recuperer le dernier prix applicable pour le Tsena e la date de la facture
        cursor.execute("""
            SELECT TOP 1 prix_m2 
            FROM historique_prix 
            WHERE tsena_id = ? AND date_creation <= ?
            ORDER BY date_creation DESC
        """, (tsena_id, current_date))
        price_row = cursor.fetchone()
        if price_row is None:
            # Si aucun prix n'est trouve, on definit un prix par defaut (ici 0)
            prix_unitaire = 0
        else:
            prix_unitaire = price_row[0]
        montant_total = prix_unitaire * surface

        cursor.execute("""
            INSERT INTO facture (mois, annee, prix_unitaire, surface, montant_total, contrat_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (current_date.month, current_date.year, prix_unitaire, surface, montant_total, contract_id))
        conn.commit()

        # Passer au mois suivant
        year = current_date.year
        month = current_date.month
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1
        current_date = datetime(year, month, 1).date()
    
    conn.close()
    return "Factures generees."

@app.route('/nouveau_contrat', methods=['GET', 'POST'])
def contrat():
    message = None
    # Pour le formulaire, on recupere la liste des boxes (ici on affiche juste l'ID et le numero)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, numero FROM box")
    boxes = cursor.fetchall()
    conn.close()
    
    if request.method == 'POST':
        try:
            box_id = int(request.form['box_id'])
            proprietaire_id = int(request.form['proprietaire_id'])
            date_debut = datetime.strptime(request.form['date_debut'], '%Y-%m-%d').date()
            date_fin = datetime.strptime(request.form['date_fin'], '%Y-%m-%d').date()
        except Exception as e:
            message = "Erreur dans les donnees saisies: " + str(e)
            return render_template('contrat.html', boxes=boxes, message=message)
        
        # Verifier si un contrat existe deje pour ce box
        if contract_exists(box_id):
            message = "Erreur : Un contrat actif existe deje pour ce box."
        else:
            # Inserer le contrat
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO contrat (date_debut, date_fin, box_id, proprietaire_id)
                VALUES (?, ?, ?, ?)
            """, (date_debut, date_fin, box_id, proprietaire_id))
            conn.commit()
            # Recuperer l'ID du contrat insere (ici on suppose que c'est le MAX(id))
            cursor.execute("SELECT MAX(id) FROM contrat")
            contract_id = cursor.fetchone()[0]
            conn.close()
            
            # Generer les factures pour chaque mois du contrat
            invoice_message = generate_invoices(contract_id, box_id, date_debut, date_fin)
            message = "Contrat cree et " + invoice_message

    return render_template('contrat.html', boxes=boxes, message=message)

if __name__ == '__main__':
    app.run(debug=True)
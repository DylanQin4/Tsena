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
            return render_template('paiement.html', box=box, error="Le montant doit etre superieur à 0")

        # Requete pour obtenir les factures non entierement payees pour ce box, ordonnees par annee et mois
        query = """
        SELECT 
            f.id, 
            f.montant_total, 
            f.mois, 
            f.annee,
            (f.montant_total - IIf(IsNull(SUM(p.montant)), 0, SUM(p.montant))) AS montant_restant
        FROM facture f
        LEFT JOIN paiement p ON f.id = p.facture_id
        WHERE f.contrat_id IN (SELECT id FROM contrat WHERE box_id = ?)
        GROUP BY f.id, f.montant_total, f.mois, f.annee
        HAVING (f.montant_total - IIf(IsNull(SUM(p.montant)), 0, SUM(p.montant))) > 0
        ORDER BY f.annee, f.mois
        """
        cursor.execute(query, (box_id,))
        unpaid_factures = cursor.fetchall()

        if not unpaid_factures:
            conn.close()
            return render_template('paiement.html', box=box, message="Aucune facture non payee pour ce box.")

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
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT 
        b.id, 
        b.numero, 
        b.longueur, 
        b.largeur,
        (SELECT nom FROM proprietaire WHERE id = b.proprietaire_id) AS proprietaire_nom,
        (SELECT prenom FROM proprietaire WHERE id = b.proprietaire_id) AS proprietaire_prenom,
        (SELECT nom FROM tsena WHERE id = b.tsena_id) AS tsena_nom,
        (SELECT prix_m2 FROM prix_loyer 
         WHERE tsena_id = b.tsena_id AND mois_debut <= ? AND mois_fin >= ?
        ) AS prix_m2,
        (
         SELECT f.montant_total - IIf(IsNull((SELECT SUM(p.montant) FROM paiement p WHERE p.facture_id = f.id)), 0, (SELECT SUM(p.montant) FROM paiement p WHERE p.facture_id = f.id))
         FROM facture f
         WHERE f.contrat_id IN (SELECT id FROM contrat WHERE box_id = b.id)
           AND f.mois = ? AND f.annee = ?
        ) AS montant_restant
    FROM box b
    """
    cursor.execute(query, (mois, mois, mois, annee))
    boxes = cursor.fetchall()
    conn.close()

    # Organiser les box par Tsena
    tsena_boxes = {}
    for box in boxes:
        tsena_nom = box[6]  # Le nom du Tsena
        if tsena_nom not in tsena_boxes:
            tsena_boxes[tsena_nom] = []
        tsena_boxes[tsena_nom].append(box)
    
    return render_template('index.html', boxes=boxes, tsena_boxes=tsena_boxes, mois=mois, annee=annee)




def contract_exists(box_id):
    """Verifie s'il existe dejà un contrat actif pour le box (date_fin >= aujourd'hui)."""
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
        # Recuperer le prix unitaire applicable pour le mois courant depuis la table prix_loyer
        cursor.execute("""
            SELECT prix_m2 
            FROM prix_loyer 
            WHERE tsena_id = ? AND mois_debut <= ? AND mois_fin >= ?
        """, (tsena_id, current_date.month, current_date.month))
        price_row = cursor.fetchone()
        if price_row is None:
            # Si aucun prix n'est trouve, on peut soit definir un prix par defaut, soit ne pas generer de facture.
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
            return render_template('index.html', boxes=boxes, message=message)
        
        # Verifier si un contrat existe dejà pour ce box
        if contract_exists(box_id):
            message = "Erreur : Un contrat actif existe dejà pour ce box."
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

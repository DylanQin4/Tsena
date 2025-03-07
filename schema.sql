-- Active: 1736442537724@@127.0.0.1@5432@tsena
-- POSTGRESQL
CREATE DATABASE tsena;

\c tsena;

CREATE TABLE proprietaire (
    id SERIAL PRIMARY KEY,
    nom VARCHAR(255) NOT NULL,
    prenom VARCHAR(255) NOT NULL
);

CREATE TABLE tsena (
    id SERIAL PRIMARY KEY,
    nom VARCHAR(255) NOT NULL
);

CREATE TABLE box (
    id SERIAL PRIMARY KEY,
    numero VARCHAR(255) NOT NULL,
    longueur INTEGER NOT NULL,
    largeur INTEGER NOT NULL,
    proprietaire_id INTEGER REFERENCES proprietaire(id),
    tsena_id INTEGER REFERENCES tsena(id)
);

CREATE TABLE historique_prix (
    id SERIAL PRIMARY KEY,
    prix_m2 INTEGER NOT NULL,
    tsena_id INTEGER REFERENCES tsena(id),
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE contrat (
    id SERIAL PRIMARY KEY,
    date_debut DATE NOT NULL,
    date_fin DATE NOT NULL,
    box_id INTEGER REFERENCES box(id),
    proprietaire_id INTEGER REFERENCES proprietaire(id),
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE facture (
    id SERIAL PRIMARY KEY,
    mois INTEGER NOT NULL,
    annee INTEGER NOT NULL,
    prix_unitaire NUMERIC(18, 5) NOT NULL,
    surface NUMERIC(15, 2) NOT NULL,
    montant_total NUMERIC(18, 5) NOT NULL,
    contrat_id INTEGER REFERENCES contrat(id),
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE paiement (
    id SERIAL PRIMARY KEY,
    date_paiement DATE NOT NULL,
    montant NUMERIC(18, 5) NOT NULL,
    facture_id INTEGER REFERENCES facture(id),
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE VIEW v_montant_paye_par_facture AS
SELECT 
    f.id AS facture_id, 
    f.mois, 
    f.annee, 
    f.prix_unitaire, 
    f.surface, 
    f.montant_total, 
    COALESCE(SUM(p.montant), 0) AS montant_paye  -- Remplace NULL par 0
FROM facture f
LEFT JOIN paiement p ON f.id = p.facture_id
GROUP BY f.id, f.mois, f.annee, f.prix_unitaire, f.surface, f.montant_total;

CREATE OR REPLACE VIEW v_montant_restant_par_facture AS
SELECT 
    facture_id, 
    mois, 
    annee, 
    prix_unitaire, 
    surface, 
    montant_total, 
    montant_paye, 
    montant_total - montant_paye AS montant_restant
FROM v_montant_paye_par_facture;


CREATE OR REPLACE FUNCTION generate_facture()
RETURNS TRIGGER AS $$
DECLARE
    mois_courant INTEGER;
    annee_courante INTEGER;
    surface NUMERIC(15, 2);
    prix_unitaire NUMERIC(18, 5);
    montant_total NUMERIC(18, 5);
BEGIN
    -- Récupérer la surface du box
    SELECT b.longueur * b.largeur INTO surface
    FROM box b
    WHERE b.id = NEW.box_id;
    
    -- Initialiser le mois et l'année à partir de la date de début du contrat
    mois_courant := EXTRACT(MONTH FROM NEW.date_debut);
    annee_courante := EXTRACT(YEAR FROM NEW.date_debut);
    
    -- Boucle pour générer une facture pour chaque mois du contrat
    WHILE (mois_courant <= EXTRACT(MONTH FROM NEW.date_fin) AND annee_courante <= EXTRACT(YEAR FROM NEW.date_fin)) LOOP
        -- Récupérer le prix du loyer applicable pour le mois en cours
        SELECT pl.prix_m2 INTO prix_unitaire
        FROM prix_loyer pl
        JOIN box b ON NEW.box_id = b.id
        JOIN tsena t ON b.tsena_id = t.id
        WHERE pl.tsena_id = t.id
        AND pl.mois_debut <= mois_courant
        AND pl.mois_fin >= mois_courant
        LIMIT 1;
        
        -- Calculer le montant total
        montant_total := prix_unitaire * surface;

        -- Insérer la facture pour le mois en cours
        INSERT INTO facture (mois, annee, prix_unitaire, surface, montant_total, contrat_id)
        VALUES (mois_courant, annee_courante, prix_unitaire, surface, montant_total, NEW.id);

        -- Passer au mois suivant
        IF mois_courant = 12 THEN
            mois_courant := 1;
            annee_courante := annee_courante + 1;
        ELSE
            mois_courant := mois_courant + 1;
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS generate_facture_trigger ON contrat;

CREATE TRIGGER generate_facture_trigger
AFTER INSERT ON contrat
FOR EACH ROW
EXECUTE FUNCTION generate_facture();



INSERT INTO proprietaire (nom, prenom) VALUES
('Randrianarisoa', 'Jean'),
('Rasolofomanana', 'Hery'),
('Rakoto', 'Faly'),
('Andrianantenaina', 'Mamy'),
('Ravelojaona', 'Tiana'),
('Rakotondrabe', 'Solofo'),
('Andriamahenintsoa', 'Bako'),
('Razafindramanga', 'Haja'),
('Rabe', 'Tojo'),
('Ratsimbazafy', 'Lova');

INSERT INTO tsena (nom) VALUES
('Tsenan''Andravoahangy'),
('Tsenan''Isotry');

INSERT INTO box (numero, longueur, largeur, proprietaire_id, tsena_id) VALUES
('A1', 3, 2, 1, 1), ('A2', 3, 2, 2, 1), ('A3', 4, 3, 3, 1), ('A4', 3, 3, 4, 1), ('A5', 5, 3, 5, 1),
('A6', 4, 2, 6, 1), ('A7', 3, 2, 7, 1), ('A8', 3, 3, 8, 1), ('A9', 4, 3, 9, 1), ('A10', 5, 3, 10, 1),
('B1', 3, 2, 1, 2), ('B2', 3, 2, 2, 2), ('B3', 4, 3, 3, 2), ('B4', 3, 3, 4, 2), ('B5', 5, 3, 5, 2),
('B6', 4, 2, 6, 2), ('B7', 3, 2, 7, 2), ('B8', 3, 3, 8, 2), ('B9', 4, 3, 9, 2), ('B10', 5, 3, 10, 2);

INSERT INTO prix_loyer (prix_m2, tsena_id, mois_debut, mois_fin) VALUES
(12000, 1, 1, 3),
(15000, 1, 4, 4),
(10000, 1, 5, 5),
(15000, 1, 6, 6),
(10000, 1, 7, 11),
(15000, 1, 12, 12),
(13000, 2, 1, 3),
(16000, 2, 4, 4),
(11000, 2, 5, 5),
(16000, 2, 6, 6),
(11000, 2, 7, 11),
(16000, 2, 12, 12);

INSERT INTO contrat (date_debut, date_fin, box_id, proprietaire_id) VALUES
('2024-01-01', '2024-12-31', 1, 1);
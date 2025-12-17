import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import csv
from collections import Counter, defaultdict
import re

# On tente d'importer pandas pour l'automatisation Excel
try:
    import pandas as pd
    PANDAS_INSTALLED = True
except ImportError:
    PANDAS_INSTALLED = False

# --- DICTIONNAIRE DE SERVICES ---
SERVICES_PORTS = {
    "80": "HTTP", "443": "HTTPS", "8080": "HTTP-ALT",
    "22": "SSH", "21": "FTP", "23": "TELNET",
    "53": "DNS", "25": "SMTP", "110": "POP3",
    "3306": "MYSQL", "123": "NTP"
}

def nommer_service(port):
    return f"{port} ({SERVICES_PORTS.get(port, 'Autre')})"

def extraire_donnees(ligne):
    regex = r"(\d{2}:\d{2}:\d{2}).*IP\s+([\w\.-]+)\s+>\s+([\w\.-]+):\s+(?:Flags\s+\[(\w+)\],)?.*length\s+(\d+)"
    match = re.search(regex, ligne)
    if match:
        heure, src_full, dst_full, flag, taille = match.groups()
        src_parts = src_full.rsplit('.', 1)
        src_ip = src_parts[0]
        src_port = src_parts[1] if len(src_parts) > 1 else "N/A"
        dst_parts = dst_full.rsplit('.', 1)
        dst_ip = dst_parts[0]
        dst_port = dst_parts[1] if len(dst_parts) > 1 else "N/A"
        return {
            "heure": heure, "minute": heure[:5],
            "src_ip": src_ip, "src_port": src_port,
            "dst_ip": dst_ip, "dst_port": dst_port,
            "flag": flag if flag else ".", "taille": int(taille)
        }
    return None

def lancer_analyse():
    try:
        S_SYN = int(entry_syn.get())
        S_VOL = int(entry_vol.get())
        S_SCAN = int(entry_scan.get())
    except ValueError:
        messagebox.showerror("Erreur", "Veuillez entrer des seuils numériques valides.")
        return

    chemin = filedialog.askopenfilename(filetypes=[("Fichiers Logs", "*.txt"), ("Tous", "*.*")])
    if not chemin: return

    txt_rapport.config(state=tk.NORMAL)
    txt_rapport.delete("1.0", tk.END)
    barre_progression.start(10)

    stats = {
        "total_paquets": 0, "total_volume": 0,
        "flux_paquets": Counter(), "flux_volume": Counter(),
        "syn_par_src": Counter(), "ports_par_src": defaultdict(set),
        "trafic_par_minute": Counter()
    }
    
    global DONNEES_CSV
    DONNEES_CSV = []

    try:
        with open(chemin, 'r', encoding='utf-8', errors='ignore') as f:
            for ligne in f:
                d = extraire_donnees(ligne)
                if d:
                    stats["total_paquets"] += 1
                    stats["total_volume"] += d["taille"]
                    flux = (d["src_ip"], d["dst_ip"])
                    stats["flux_paquets"][flux] += 1
                    stats["flux_volume"][flux] += d["taille"]
                    stats["trafic_par_minute"][d["minute"]] += d["taille"]
                    if "S" in d["flag"]:
                        stats["syn_par_src"][d["src_ip"]] += 1
                    if d["dst_port"] != "N/A":
                        stats["ports_par_src"][d["src_ip"]].add(d["dst_port"])
                    d["service_dst"] = nommer_service(d["dst_port"])
                    DONNEES_CSV.append(d)

        barre_progression.stop()
        if stats["total_paquets"] == 0:
            messagebox.showwarning("Info", "Aucun paquet trouvé.")
            return

        generer_rapport_markdown(chemin, stats, S_SYN, S_VOL, S_SCAN)
        btn_csv.config(state=tk.NORMAL)
        if PANDAS_INSTALLED:
            btn_excel_auto.config(state=tk.NORMAL)

    except Exception as e:
        barre_progression.stop()
        messagebox.showerror("Crash", f"Erreur critique : {e}")

def generer_rapport_markdown(chemin, stats, s_syn, s_vol, s_scan):
    top_flux = stats["flux_paquets"].most_common(12)
    # ALIGNEMENT DYNAMIQUE
    max_len_src = max([len(src) for (src, dst), _ in top_flux] + [len("SOURCE")])
    max_len_dst = max([len(dst) for (src, dst), _ in top_flux] + [len("DESTINATION")])
    L_SRC, L_DST, L_VOL = max_len_src + 2, max_len_dst + 2, 15
    
    pic_minute, pic_vol = stats["trafic_par_minute"].most_common(1)[0]
    
    md = f"# RAPPORT D'AUDIT RÉSEAU (SAÉ 1.05)\n"
    md += f"**Fichier** : {os.path.basename(chemin)}\n"
    md += f"**Paquets** : {stats['total_paquets']} | **Volume** : {stats['total_volume']/1024:.2f} Ko\n"
    md += f"**Pic de charge** : {pic_minute} avec {pic_vol/1024:.2f} Ko\n"
    md += "=" * (L_SRC + L_DST + L_VOL + 15) + "\n\n"

    md += "## 1. TOP FLUX & SATURATION\n"
    md += f"| {'SOURCE':<{L_SRC}} | {'DESTINATION':<{L_DST}} | {'VOLUME (o)':<{L_VOL}} | {'STATUT'} |\n"
    md += f"| {'-'*L_SRC} | {'-'*L_DST} | {'-'*L_VOL} | {'-'*10} |\n"
    
    anomalies = []
    for (src, dst), count in top_flux:
        vol = stats["flux_volume"][(src, dst)]
        statut = "OK"
        if vol > s_vol:
            statut = "🚨 SATURÉ"
            anomalies.append(f"SATURATION BANDE PASSANTE : {src} -> {dst}")
        md += f"| {src:<{L_SRC}} | {dst:<{L_DST}} | {vol:<{L_VOL}} | {statut} |\n"

    md += "\n## 2. ANALYSE SÉCURITÉ (MENACES)\n"
    md += f"- **Analyse SYN Flood** (Seuil: {s_syn}):\n"
    syn_detecte = False
    for ip, count in stats["syn_par_src"].items():
        if count > s_syn:
            md += f"  - ⚠️  {ip} : {count} paquets SYN (Attaque probable)\n"
            anomalies.append(f"SYN FLOOD : {ip}")
            syn_detecte = True
    if not syn_detecte: md += "  - Aucun SYN Flood détecté.\n"

    md += f"\n- **Analyse Scan de Ports** (Seuil: {s_scan}):\n"
    scan_detecte = False
    for ip, ports in stats["ports_par_src"].items():
        if len(ports) > s_scan:
            md += f"  - 🔍  {ip} a scanné {len(ports)} ports différents.\n"
            anomalies.append(f"PORT SCANNING : {ip}")
            scan_detecte = True
    if not scan_detecte: md += "  - Aucun scan détecté.\n"

    md += "\n## CONCLUSION DE L'AUDIT\n"
    if anomalies:
        md += ">>> LE RÉSEAU EST COMPROMIS. ACTIONS REQUISES :\n"
        for a in set(anomalies): md += f"- [ ] Bloquer/Investiguer {a}\n"
        lbl_status.config(text="⚠ MENACES CRITIQUES", fg="red")
    else:
        md += ">>> LE RÉSEAU EST STABLE.\n"
        lbl_status.config(text="✔ Réseau Sain", fg="green")

    txt_rapport.insert(tk.END, md)
    txt_rapport.config(state=tk.DISABLED)

def exporter_excel_automatique():
    path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
    if not path: return
    try:
        df = pd.DataFrame(DONNEES_CSV)
        with pd.ExcelWriter(path, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Donnees_Brutes', index=False)
            workbook = writer.book
            
            # Onglet Saturation
            sheet_sat = workbook.add_worksheet('Saturation')
            top_sat = df.groupby('src_ip')['taille'].sum().sort_values(ascending=False).head(8).reset_index()
            for i, col in enumerate(top_sat.columns):
                sheet_sat.write(0, i, col)
                for j, v in enumerate(top_sat[col]): sheet_sat.write(j+1, i, v)
            chart_pie = workbook.add_chart({'type': 'pie'})
            chart_pie.add_series({'categories': ['Saturation', 1, 0, len(top_sat), 0], 'values': ['Saturation', 1, 1, len(top_sat), 1]})
            chart_pie.set_title({'name': 'Top Consommation (Octets)'})
            sheet_sat.insert_chart('D2', chart_pie)

            # Onglet SYN Flood
            sheet_sec = workbook.add_worksheet('Securite_SYN')
            df_syn = df[df['flag'].str.contains('S', na=False)]
            top_syn = df_syn['src_ip'].value_counts().head(8).reset_index()
            if not top_syn.empty:
                top_syn.columns = ['IP', 'Nb_SYN']
                for i, col in enumerate(top_syn.columns):
                    sheet_sec.write(0, i, col)
                    for j, v in enumerate(top_syn[col]): sheet_sec.write(j+1, i, v)
                chart_bar = workbook.add_chart({'type': 'column'})
                chart_bar.add_series({'categories': ['Securite_SYN', 1, 0, len(top_syn), 0], 'values': ['Securite_SYN', 1, 1, len(top_syn), 1], 'fill': {'color': '#C0392B'}})
                chart_bar.set_title({'name': 'Attaques SYN par IP'})
                sheet_sec.insert_chart('D2', chart_bar)
        messagebox.showinfo("Succès", "Fichier Excel généré avec graphiques !")
    except Exception as e:
        messagebox.showerror("Erreur Excel", f"Erreur : {e}")

def exporter_csv():
    path = filedialog.asksaveasfilename(defaultextension=".csv")
    if path:
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            fields = ["heure", "minute", "src_ip", "src_port", "dst_ip", "dst_port", "service_dst", "flag", "taille"]
            writer = csv.DictWriter(f, fieldnames=fields, delimiter=';')
            writer.writeheader()
            writer.writerows(DONNEES_CSV)
        messagebox.showinfo("Succès", "CSV exporté avec succès.")

# --- GUI ---
root = tk.Tk()
root.title("Audit Réseau Pro - SAÉ 1.05")
root.geometry("1200x850")
root.configure(bg="#f0f0f0")

tk.Label(root, text="AUDIT RÉSEAU & DÉTECTION D'INTRUSION", font=("Segoe UI", 16, "bold"), bg="#f0f0f0").pack(pady=10)
frame_conf = tk.LabelFrame(root, text="Configuration des Seuils", bg="#f0f0f0", padx=10, pady=5)
frame_conf.pack(fill="x", padx=20)

tk.Label(frame_conf, text="Seuil SYN:", bg="#f0f0f0").pack(side="left")
entry_syn = tk.Entry(frame_conf, width=5); entry_syn.insert(0, "20"); entry_syn.pack(side="left", padx=5)
tk.Label(frame_conf, text="Seuil Volume (o):", bg="#f0f0f0").pack(side="left")
entry_vol = tk.Entry(frame_conf, width=10); entry_vol.insert(0, "800000"); entry_vol.pack(side="left", padx=5)
tk.Label(frame_conf, text="Seuil Scan:", bg="#f0f0f0").pack(side="left")
entry_scan = tk.Entry(frame_conf, width=5); entry_scan.insert(0, "15"); entry_scan.pack(side="left", padx=5)

tk.Button(frame_conf, text="1. ANALYSER LOGS", command=lancer_analyse, bg="#2c3e50", fg="white", font=("Segoe UI", 10, "bold")).pack(side="right", padx=10)
btn_csv = tk.Button(frame_conf, text="2. EXPORTER CSV", command=exporter_csv, state="disabled", bg="#7f8c8d", fg="white")
btn_csv.pack(side="right", padx=10)
btn_excel_auto = tk.Button(frame_conf, text="3. EXCEL AUTO (GRAPHES)", command=exporter_excel_automatique, state="disabled", bg="#27ae60", fg="white", font=("Segoe UI", 10, "bold"))
btn_excel_auto.pack(side="right", padx=10)

barre_progression = ttk.Progressbar(root, orient="horizontal", length=1100, mode="indeterminate")
barre_progression.pack(pady=5)
txt_rapport = tk.Text(root, font=("Consolas", 10), bg="white", padx=10, pady=10)
txt_rapport.pack(fill="both", expand=True, padx=20)
lbl_status = tk.Label(root, text="Prêt", font=("Segoe UI", 12, "bold"), bg="#f0f0f0", fg="gray")
lbl_status.pack(pady=10)

if not PANDAS_INSTALLED:
    messagebox.showinfo("Installation", "Pour le bouton EXCEL AUTO, installez pandas via : pip install pandas xlsxwriter")

root.mainloop()
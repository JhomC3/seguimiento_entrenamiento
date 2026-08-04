import sqlite3
import pandas as pd
import numpy as np
from src.metrics_engine import calculate_pfr_timeline, is_compound

def run_diagnostics(db_path: str, filter_type: str = "systemic", filter_value: str = None) -> list:
    """
    Ejecuta diagnósticos lógicos autorreferenciales basados en el rendimiento del atleta.
    Compara las métricas del usuario con su propio historial para encontrar las causas de estancamiento.
    Retorna una lista de alertas con el formato:
    {
        'id': '...',
        'titulo': '...',
        'severidad': 'danger|warning|info',
        'mensaje': '...',
        'recomendacion': '...'
    }
    """
    # 1. Obtener la línea de tiempo PFR diaria
    timeline = calculate_pfr_timeline(db_path, filter_type, filter_value)
    
    if timeline.empty or len(timeline) < 7:
        return []
        
    alerts = []
    
    # Datos de las últimas 2 semanas para el diagnóstico comparativo
    last_14_days = timeline.tail(14).copy()
    last_7_days = timeline.tail(7).copy()
    
    # Medias de rendimiento
    avg_perf_last_7 = last_7_days["rendimiento"].mean()
    avg_perf_prev_7 = last_14_days.head(7)["rendimiento"].mean()
    perf_delta = avg_perf_last_7 - avg_perf_prev_7
    
    # Medias de fatiga y recuperación
    avg_fatigue_last_7 = last_7_days["fatiga_acumulada"].mean()
    
    # -----------------------------------------------------------------
    # REGLA 1: FATIGA ACUMULADA EXCESIVA (Overreaching No Funcional)
    # -----------------------------------------------------------------
    # Se dispara si la fatiga sistémica acumulada promedio es alta y la fuerza cae
    if avg_fatigue_last_7 > 50.0 and perf_delta < -0.4:
        target_name = filter_value if filter_value else "todo el cuerpo"
        alerts.append({
            "id": "overreaching",
            "titulo": "Fatiga Acumulada Excesiva (SNC/Músculo)",
            "severidad": "danger",
            "mensaje": f"El rendimiento en {target_name} ha caído un {abs(perf_delta):.1f}% en las últimas 2 semanas debido a que tu índice de fatiga media se mantiene crítico en {avg_fatigue_last_7:.1f} pts.",
            "recomendacion": "Tu cuerpo no se está adaptando al volumen actual. Programa una semana de descarga (Deload) reduciendo a la mitad las series de tus entrenamientos y dejando al menos 2-3 repeticiones en reserva (RIR > 2)."
        })

    # -----------------------------------------------------------------
    # REGLA 2: INTERFERENCIA DE FRECUENCIA (Falta de Descanso)
    # -----------------------------------------------------------------
    # Aplica a grupos musculares y ejercicios. Identifica si entrenas con fatiga previa y la fuerza baja.
    if filter_type in ["muscle_group", "exercise"]:
        training_days = last_14_days[last_14_days["sets_totales"] > 0]
        if len(training_days) >= 2:
            for idx in range(1, len(training_days)):
                prev_row = training_days.iloc[idx-1]
                curr_row = training_days.iloc[idx]
                
                days_between = (curr_row["fecha_dt"] - prev_row["fecha_dt"]).days
                
                # Si se entrenó con 1 o 2 días de descanso y el rendimiento cayó significativamente respecto al anterior
                if days_between <= 2 and curr_row["rendimiento"] < prev_row["rendimiento"] - 0.8:
                    target_name = filter_value if filter_value else "este ejercicio"
                    alerts.append({
                        "id": "insufficient_rest",
                        "titulo": "Frecuencia Excesiva / Poco Descanso",
                        "severidad": "warning",
                        "mensaje": f"Caída de rendimiento detectada en la sesión del {curr_row['fecha']} para {target_name} (fuerza bajó un {(prev_row['rendimiento'] - curr_row['rendimiento']):.1f}% con solo {days_between} días de descanso desde el entrenamiento previo del {prev_row['fecha']}).",
                        "recomendacion": f"Espera un mínimo de 72 horas (3 días enteros de descanso) antes de volver a estimular intensamente este grupo muscular para permitir la regeneración estructural de las fibras."
                    })
                    break # Añadimos solo una alerta de este tipo para no saturar

    # -----------------------------------------------------------------
    # REGLA 3: VOLUMEN NO PRODUCTIVO (Junk Volume / Exceso de Series)
    # -----------------------------------------------------------------
    if filter_type == "muscle_group" and filter_value:
        total_sets_14 = last_14_days["sets_totales"].sum()
        weekly_sets_avg = total_sets_14 / 2.0
        
        # Si las series semanales medias para ese grupo superan 16 y el rendimiento se estanca (delta plano)
        if weekly_sets_avg > 16.0 and abs(perf_delta) < 0.2:
            alerts.append({
                "id": "junk_volume",
                "titulo": "Volumen de Series Excesivo (Junk Volume)",
                "severidad": "warning",
                "mensaje": f"Estás promediando {weekly_sets_avg:.1f} series semanales para {filter_value}, pero tu rendimiento de fuerza relativa está completamente estancado (cambio de apenas {perf_delta:+.1f}%).",
                "recomendacion": "Estás haciendo más volumen del que tu músculo puede asimilar efectivamente. El volumen sobrante actúa como fatiga estéril. Prueba reduciendo tu volumen semanal a 10-12 series, incrementando el RIR o enfocándote en la calidad de la contracción."
            })

    # -----------------------------------------------------------------
    # REGLA 4: VOLUMEN INSUFICIENTE (Estímulo Inadecuado)
    # -----------------------------------------------------------------
    if filter_type == "muscle_group" and filter_value:
        total_sets_14 = last_14_days["sets_totales"].sum()
        weekly_sets_avg = total_sets_14 / 2.0
        
        # Si las series semanales medias para ese grupo son menores a 5 y el rendimiento está plano
        if weekly_sets_avg < 5.0 and abs(perf_delta) < 0.2:
            alerts.append({
                "id": "under_volume",
                "titulo": "Volumen Insuficiente (Falta de Estímulo)",
                "severidad": "info",
                "mensaje": f"Estás promediando únicamente {weekly_sets_avg:.1f} series semanales para {filter_value}. Tu rendimiento de fuerza se mantiene totalmente plano.",
                "recomendacion": "Tu volumen actual está por debajo de tu umbral de adaptación activa. Para ver ganancias y progresión de sobrecarga, incrementa el volumen a 8-10 series semanales bien distribuidas."
            })

    # -----------------------------------------------------------------
    # REGLA 5: EXCESO DE FALLO EN COMPUESTOS (SNC Drained)
    # -----------------------------------------------------------------
    if filter_type == "systemic":
        conn = sqlite3.connect(db_path)
        # Buscar el RIR de ejercicios compuestos de las últimas 2 semanas
        query = """
            SELECT t.rir, t.ejercicio
            FROM training_sets t
            WHERE t.rir IS NOT NULL AND t.kg IS NOT NULL
            ORDER BY t.semana DESC, t.fecha DESC
            LIMIT 50
        """
        sets_df = pd.read_sql_query(query, conn)
        conn.close()
        
        if not sets_df.empty:
            sets_df["is_compuesto"] = sets_df["ejercicio"].apply(is_compound)
            compound_sets = sets_df[sets_df["is_compuesto"]]
            
            if len(compound_sets) >= 6:
                avg_rir_compounds = compound_sets["rir"].mean()
                # Si el RIR medio de compuestos es menor a 1.0 (entrenar al fallo constantemente)
                if avg_rir_compounds < 1.0:
                    alerts.append({
                        "id": "cns_drain",
                        "titulo": "Exceso de Fallo en Multiarticulares (Drenaje SNC)",
                        "severidad": "danger",
                        "mensaje": f"Tu RIR medio en ejercicios multiarticulares pesados es de {avg_rir_compounds:.1f} (muy cercano al fallo absoluto). Esto drena desproporcionadamente tu SNC.",
                        "recomendacion": "Llevar ejercicios compuestos (ej. Hack, Sentadillas, Prensa) al fallo absoluto genera una fatiga central inmensa sin darte estímulo extra. Entrena estos movimientos pesados manteniendo un RIR de 1 o 2, y reserva el fallo absoluto (RIR 0) solo para las poleas o máquinas de aislamiento."
                    })

    return alerts

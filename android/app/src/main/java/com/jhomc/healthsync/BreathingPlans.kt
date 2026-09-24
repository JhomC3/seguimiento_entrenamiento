package com.jhomc.healthsync

import org.json.JSONArray
import org.json.JSONObject

/**
 * Planillas de respiración en prefs (JSON versionado, tope 8). Sin Room: la
 * tabla se retiró en la migración 13→14 y una planilla es solo la config
 * actual con nombre. Lo corrupto se salta, nunca rompe la carga.
 */
object BreathingPlans {

    const val MAX = 8
    const val VERSION = 1

    data class Plan(
        val nombre: String,
        val pattern: BreathingPattern,
        val duracionS: Int?,
        val timbre: SoundStyle,
    )

    fun load(json: String): List<Plan> {
        if (json.isBlank()) return emptyList()
        return runCatching {
            val root = JSONObject(json)
            if (root.optInt("v", 0) != VERSION) return emptyList()
            val arr = root.optJSONArray("planes") ?: return emptyList()
            (0 until arr.length()).mapNotNull { i ->
                runCatching { parse(arr.getJSONObject(i)) }.getOrNull()
            }
        }.getOrDefault(emptyList())
    }

    fun dump(plans: List<Plan>): String {
        val arr = JSONArray()
        for (p in plans.take(MAX)) {
            arr.put(
                JSONObject()
                    .put("nombre", p.nombre)
                    .put("pattern", p.pattern.toJson())
                    .put("duracion_s", p.duracionS ?: JSONObject.NULL)
                    .put("timbre", p.timbre.name),
            )
        }
        return JSONObject().put("v", VERSION).put("planes", arr).toString()
    }

    /** Añade o reemplaza por nombre; null si está lleno con otro nombre. */
    fun add(plans: List<Plan>, plan: Plan): List<Plan>? {
        val nombre = plan.nombre.trim()
        if (nombre.isEmpty()) return null
        val rest = plans.filter { it.nombre != nombre }
        if (rest.size >= MAX) return null
        return rest + plan.copy(nombre = nombre)
    }

    fun remove(plans: List<Plan>, nombre: String): List<Plan> =
        plans.filter { it.nombre != nombre }

    private fun parse(o: JSONObject): Plan {
        val nombre = o.getString("nombre")
        require(nombre.isNotBlank())
        return Plan(
            nombre = nombre,
            pattern = BreathingPattern.fromJson(o.getJSONObject("pattern")),
            duracionS = if (o.isNull("duracion_s")) null else o.getInt("duracion_s"),
            timbre = runCatching { SoundStyle.valueOf(o.optString("timbre", "AIRE")) }
                .getOrDefault(SoundStyle.AIRE),
        )
    }
}

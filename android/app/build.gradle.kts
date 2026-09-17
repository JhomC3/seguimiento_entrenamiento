plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp") version "2.1.0-1.0.29"
}

android {
    namespace = "com.jhomc.healthsync"
    compileSdk = 36

    buildFeatures {
        buildConfig = true
    }

    defaultConfig {
        applicationId = "com.jhomc.healthsync"
        minSdk = 26
        targetSdk = 36
        // 2/0.2.0: fix 400 (cuarentena+bisección) + agregados horarios *_H1.
        // 4/0.3.0: escritura nutricional a Health Connect (permiso WRITE_NUTRITION).
        // Subir versionCode en cada build entregado: es la única forma de
        // distinguir APKs en Ajustes.
        versionCode = 4
        versionName = "0.3.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildTypes {
        debug {
            // Destino preconfigurado (solo debug): la app funciona sin tocar
            // nada. El token se lee del archivo gitignored del repo (fuente
            // única con el servidor); si falta, queda vacío y la app lo avisa.
            val token = syncDefaultToken()
            buildConfigField("String", "DEFAULT_SYNC_URL", "\"http://192.168.1.6:8000/sync/health-connect\"")
            buildConfigField("String", "DEFAULT_SYNC_TOKEN", "\"${token.escapeForKotlin()}\"")
            // Base explícita de la API v1 del diario (sin derivar por strip en
            // el caso común debug; ver TrainingApiClient.resolveApiBase).
            buildConfigField("String", "DEFAULT_API_BASE", "\"http://192.168.1.6:8000\"")
        }
        release {
            // Nunca embebir el secreto en un APK distribuible: release exige
            // configuración manual (o pairing QR futuro) para sincronizar.
            buildConfigField("String", "DEFAULT_SYNC_URL", "\"\"")
            buildConfigField("String", "DEFAULT_SYNC_TOKEN", "\"\"")
            buildConfigField("String", "DEFAULT_API_BASE", "\"\"")
        }
    }
}

fun syncDefaultToken(): String {
    // OJO: el root del proyecto Gradle es android/ (ahí vive settings.gradle),
    // no la raíz del repo. project.file() resuelve contra android/app/.
    // Ambas formas llegan a <repo>/data/hc_sync_token; con "data/..." a secas
    // se apuntaba a android/[app/]data/... (inexistente) y el debug salía con
    // token vacío -> "sin_destino" en cada sync.
    val file = rootProject.file("../data/hc_sync_token")
    return if (file.exists()) file.readText().trim() else ""
}

fun String.escapeForKotlin(): String =
    replace("\\", "\\\\").replace("\"", "\\\"").replace("$", "\\$")

dependencies {
    implementation("androidx.health.connect:connect-client:1.1.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("androidx.test:core:1.6.1")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
